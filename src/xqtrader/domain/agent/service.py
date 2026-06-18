"""Agent 薄 API 业务逻辑。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import HTTPException, Request

from framework.config.settings import settings
from xqtrader.domain.agent.protocol import MetaField, RunStatus, sse_event_name
from xqtrader.domain.agent.redis_bus import AgentRedisBus
from xqtrader.domain.agent.schemas import (
    CreateSessionRequest,
    RunStatusResponse,
    RunTask,
    SessionResponse,
    SubmitMessageRequest,
    SubmitMessageResponse,
)
from xqtrader.domain.agent.utils import new_id


class AgentService:
    def __init__(self) -> None:
        self._bus = AgentRedisBus()

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
        run_id = new_id("run")
        model = body.model or session.model or settings.AGENT.AGENT_DEFAULT_MODEL or None
        trace_id = request.headers.get("X-Trace-Id")
        task = RunTask(
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            message=body.content,
            model=model,
            trace_id=trace_id,
            context=body.context,
        )
        await self._bus.enqueue_run(task)
        return SubmitMessageResponse(
            run_id=run_id,
            session_id=session_id,
            status=RunStatus.QUEUED,
        )

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
