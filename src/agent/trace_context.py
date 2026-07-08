"""Agent Run 追踪上下文 — trace_id / run_id 贯穿 Worker 日志与 Redis 事件。"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

_trace_id: ContextVar[str | None] = ContextVar("agent_trace_id", default=None)
_run_id: ContextVar[str | None] = ContextVar("agent_run_id", default=None)


@dataclass(frozen=True, slots=True)
class RunTraceContext:
    run_id: str
    trace_id: str | None = None


def set_run_trace(ctx: RunTraceContext) -> None:
    _run_id.set(ctx.run_id)
    _trace_id.set(ctx.trace_id)


def clear_run_trace() -> None:
    _run_id.set(None)
    _trace_id.set(None)


def get_trace_id() -> str | None:
    return _trace_id.get()


def get_run_id() -> str | None:
    return _run_id.get()


def trace_fields() -> dict[str, str]:
    """供日志 extra 或 Redis payload 附带的追踪字段。"""
    fields: dict[str, str] = {}
    run_id = get_run_id()
    trace_id = get_trace_id()
    if run_id:
        fields["run_id"] = run_id
    if trace_id:
        fields["trace_id"] = trace_id
    return fields
