"""Agent 薄 API 业务逻辑。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import HTTPException, Request

from framework.commons.logger import get_logger
from framework.config.settings import settings
from xqtrader.domain.agent.intent_router import CoachRoute, IntentRouter, WorkflowRoute
from xqtrader.domain.agent.models.session import AgentMessage
from xqtrader.domain.agent.protocol import MetaField, RunStatus, sse_event_name
from xqtrader.domain.agent.redis_bus import AgentRedisBus
from xqtrader.domain.agent.schemas import (
    CreateSessionRequest,
    HistoryMessage,
    RunStatusResponse,
    RunTask,
    SessionHistoryResponse,
    SessionResponse,
    SubmitMessageRequest,
    SubmitMessageResponse,
    ToolCall,
)
from xqtrader.domain.agent.utils import new_id
from xqtrader.domain.workflow.dispatch import (
    WorkflowExecutionError,
    WorkflowNotFoundError,
    execute_workflow,
)

logger = get_logger("AGENT.SERVICE")


class AgentService:
    def __init__(self) -> None:
        self._bus = AgentRedisBus()

    async def close(self) -> None:
        """关闭底层 Redis bus 连接（供应用 shutdown 调用，避免外部直接访问 _bus 私有属性）。"""
        await self._bus.close()

    @staticmethod
    def _user_context(request: Request) -> tuple[str, str]:
        user_id = request.headers.get("X-User-Id", "anonymous")
        tenant_id = request.headers.get("X-Tenant-Id", "default")
        return user_id, tenant_id

    async def create_session(
        self,
        request: Request,
        body: CreateSessionRequest,
    ) -> SessionResponse:
        user_id, tenant_id = self._user_context(request)
        session_id = new_id("sess")
        await self._bus.save_session(
            session_id,
            session_key_value=body.session_key,
            title=body.title,
            model=body.model,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        data = await self._bus.get_session(session_id)
        if not data:
            raise HTTPException(status_code=500, detail="Failed to create session")
        return SessionResponse(
            session_id=session_id,
            session_key=data.get("session_key") or session_id,
            title=data.get("title") or None,
            model=data.get("model") or None,
            created_at=data.get("created_at", ""),
        )

    async def get_session(self, session_id: str) -> SessionResponse:
        data = await self._bus.get_session(session_id)
        if not data:
            raise HTTPException(status_code=404, detail="Session not found")
        return SessionResponse(
            session_id=session_id,
            session_key=data.get("session_key") or session_id,
            title=data.get("title") or None,
            model=data.get("model") or None,
            created_at=data.get("created_at", ""),
        )

    async def submit_message(
        self,
        request: Request,
        session_id: str,
        body: SubmitMessageRequest,
    ) -> SubmitMessageResponse:
        session = await self.get_session(session_id)
        user_id, tenant_id = self._user_context(request)
        try:
            route = IntentRouter.resolve(
                body.content,
                flow_id=body.flow_id,
                context=body.context,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if isinstance(route, WorkflowRoute):
            workspace_id = str((body.context or {}).get("workspace_id") or "")
            try:
                record = await execute_workflow(
                    route.flow_id,
                    route.inputs,
                    workspace_id=workspace_id,
                )
            except WorkflowNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except WorkflowExecutionError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc

            wf_status = str(record.get("status") or "")
            if wf_status == "succeeded":
                status = RunStatus.COMPLETED
            elif wf_status == "paused":
                status = RunStatus.RUNNING
            elif wf_status == "failed":
                status = RunStatus.FAILED
            else:
                status = RunStatus.COMPLETED

            return SubmitMessageResponse(
                run_id=str(record.get("run_id") or new_id("run")),
                session_id=session_id,
                status=status,
            )

        run_id = new_id("run")
        model = body.model or session.model or settings.AGENT.AGENT_DEFAULT_MODEL or None
        trace_id = request.headers.get("X-Trace-Id")

        # CoachRoute 走 Agent Worker（同 AgentRoute），但记录场景信息并写入 context
        # 供下游 Hook / 遥测读取。人格层激活仍由 EmotionDetectHook 在 Worker 内执行。
        task_context = body.context
        if isinstance(route, CoachRoute):
            logger.info(
                "心理教练优先模式触发: session_id=%s scenario=%s intensity=%d "
                "keywords=%s",
                session_id,
                route.scenario_name,
                route.intensity,
                list(route.matched_keywords),
            )
            task_context = dict(body.context or {})
            task_context["coach_scenario"] = {
                "name": route.scenario_name,
                "intensity": route.intensity,
                "matched_keywords": list(route.matched_keywords),
            }

        task = RunTask(
            run_id=run_id,
            session_id=session_id,
            session_key=session.session_key,
            user_id=user_id,
            tenant_id=tenant_id,
            message=body.content,
            model=model,
            trace_id=trace_id,
            context=task_context,
        )
        await self._bus.enqueue_run(task)
        return SubmitMessageResponse(
            run_id=run_id,
            session_id=session_id,
            status=RunStatus.QUEUED,
        )

    async def get_history(self, session_key: str) -> SessionHistoryResponse:
        """按 session_key 从 PG 读取历史对话（含工具调用轨迹，用于 UI 回载）。"""
        rows = await AgentMessage.filter(
            session_key=session_key,
            order_by=AgentMessage.seq,
        )
        messages: list[HistoryMessage] = []
        for row in rows:
            payload = row.payload or {}
            role = payload.get("role", "")
            content = payload.get("content") or ""
            timestamp = payload.get("timestamp") or ""
            if role == "user":
                if not content:
                    continue
                messages.append(HistoryMessage(role="user", content=content, timestamp=timestamp))
            elif role == "assistant":
                raw_calls = payload.get("tool_calls")
                tool_calls = None
                if isinstance(raw_calls, list) and raw_calls:
                    tool_calls = [ToolCall.model_validate(tc) for tc in raw_calls]
                # 有文本内容或工具调用的 assistant 消息都保留
                if content or tool_calls:
                    messages.append(
                        HistoryMessage(
                            role="assistant",
                            content=content,
                            timestamp=timestamp,
                            tool_calls=tool_calls,
                        )
                    )
            elif role == "tool":
                messages.append(
                    HistoryMessage(
                        role="tool",
                        content=content,
                        timestamp=timestamp,
                        tool_call_id=payload.get("tool_call_id") or "",
                        name=payload.get("name") or "",
                    )
                )
        return SessionHistoryResponse(session_key=session_key, messages=messages)

    async def get_run_status(self, run_id: str) -> RunStatusResponse:
        meta = await self._bus.get_run_meta(run_id)
        if not meta:
            raise HTTPException(status_code=404, detail="Run not found")
        raw_status = meta.get(MetaField.STATUS.value, RunStatus.QUEUED.value)
        try:
            status = RunStatus(raw_status)
        except ValueError:
            status = RunStatus.QUEUED
        return RunStatusResponse(
            run_id=run_id,
            session_id=meta.get(MetaField.SESSION_ID.value, ""),
            status=status,
            error=meta.get(MetaField.ERROR.value) or None,
        )

    async def cancel_run(self, run_id: str) -> RunStatusResponse:
        await self._bus.request_cancel(run_id)
        return await self.get_run_status(run_id)

    async def stream_run_events(self, run_id: str) -> AsyncIterator[str]:
        """生成 SSE 文本行。"""
        meta = await self._bus.get_run_meta(run_id)
        if not meta:
            raise HTTPException(status_code=404, detail="Run not found")

        async for _msg_id, event in self._bus.iter_sse_events(
            run_id,
            block_ms=settings.AGENT.AGENT_SSE_BLOCK_MS,
            idle_timeout_s=settings.AGENT.AGENT_SSE_IDLE_TIMEOUT_S,
        ):
            name = sse_event_name(event.type)
            data = json.dumps(
                event.model_dump(),
                ensure_ascii=False,
            )
            yield f"event: {name}\ndata: {data}\n\n"
