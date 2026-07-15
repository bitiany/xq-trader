"""Harness 治理 Hook — Orchestrator 工具策略与 spawn JSON 契约校验。"""

from __future__ import annotations

from typing import Any

from nanobot.agent.hook import AgentHook, AgentHookContext

from agent.spawn_contracts import (
    SpawnContractError,
    detect_spawn_worker,
    extract_json_payload,
    validate_spawn_output,
)
from agent.trace_context import trace_fields
from framework.commons.logger import get_logger

logger = get_logger("AGENT_GOVERNANCE")

_STOCK_RESEARCH_SKILL = "stock-research"

_ORCHESTRATOR_FORBIDDEN_OPS: frozenset[str] = frozenset({
    "get_stock_fund_flow",
    "get_stock_technical",
    "get_stock_chanlun",
    "get_stock_sentiment",
})


class ToolPolicyViolationError(RuntimeError):
    """Orchestrator 调用了禁止的工具。"""


def _stock_research_policy_enabled(context: dict[str, Any] | None) -> bool:
    if not context:
        return False
    skill = str(context.get("skill") or context.get("orchestrator") or "").strip()
    if skill == _STOCK_RESEARCH_SKILL:
        return True
    page_source = str(context.get("page_source") or "").strip().lower()
    return page_source in {"stock-research", "stock_detail", "stock"}


def _match_forbidden_operation(tool_name: str) -> str | None:
    lowered = tool_name.lower().replace("-", "_")
    for op_id in _ORCHESTRATOR_FORBIDDEN_OPS:
        if op_id in lowered:
            return op_id
    return None


_SPAWN_PENDING_MARKERS = (
    "started",
    "i'll notify you when it completes",
    "i will notify you when it completes",
)


def _is_spawn_pending(detail: str) -> bool:
    """识别 spawn 异步未完成的通知文本（非最终结果）。

    nanobot spawn 工具在子 agent 启动时返回形如
    "Subagent [xxx] started (id: ...). I'll notify you when it completes." 的通知，
    此时尚未产生 JSON 输出，契约校验应跳过。
    """
    lowered = detail.lower()
    return any(marker in lowered for marker in _SPAWN_PENDING_MARKERS)


class OrchestratorToolPolicyHook(AgentHook):
    """stock-research Orchestrator 工具白名单强制（reraise 阻断 run）。"""

    def __init__(self, run_context: dict[str, Any] | None) -> None:
        super().__init__(reraise=True)
        self._enabled = _stock_research_policy_enabled(run_context)

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        if not self._enabled:
            return
        for tc in context.tool_calls:
            if tc.name == "spawn" or tc.name.endswith("_spawn"):
                continue
            op_id = _match_forbidden_operation(tc.name)
            if op_id:
                raise ToolPolicyViolationError(
                    f"stock-research Orchestrator 禁止调用 {op_id}；"
                    f"请通过 spawn 委托对应 Worker",
                )


class SpawnContractHook(AgentHook):
    """spawn Worker 成功返回后校验 JSON 契约（reraise 阻断 run）。"""

    def __init__(self, run_context: dict[str, Any] | None) -> None:
        super().__init__(reraise=True)
        self._enabled = _stock_research_policy_enabled(run_context)

    async def after_iteration(self, context: AgentHookContext) -> None:
        if not self._enabled:
            return
        for idx, ev in enumerate(context.tool_events):
            name = ev.get("name", "")
            if not (name == "spawn" or name.endswith("_spawn")):
                continue
            if ev.get("status", "ok") == "error":
                continue
            detail = str(ev.get("detail") or ev.get("result") or "").strip()
            if not detail:
                continue
            # spawn 异步执行：跳过"已启动"通知（非最终结果）
            if _is_spawn_pending(detail):
                logger.info(
                    "spawn 契约跳过：子任务尚未完成 detail=%s",
                    detail[:120],
                    extra=trace_fields(),
                )
                continue
            args: dict[str, Any] = {}
            if idx < len(context.tool_calls):
                raw_args = context.tool_calls[idx].arguments
                if isinstance(raw_args, dict):
                    args = raw_args
            task_text = str(args.get("task") or "")
            label = str(args.get("label") or "")
            worker = detect_spawn_worker(task_text, label)
            if worker is None:
                logger.warning(
                    "spawn 契约跳过：未识别 worker 类型 task=%s",
                    task_text[:80],
                    extra=trace_fields(),
                )
                continue
            try:
                payload = extract_json_payload(detail)
                validate_spawn_output(worker, payload)
            except SpawnContractError as exc:
                raise SpawnContractError(
                    f"spawn[{worker}] 输出不合规: {exc}",
                ) from exc
            logger.info(
                "spawn 契约校验通过 worker=%s",
                worker,
                extra=trace_fields(),
            )
