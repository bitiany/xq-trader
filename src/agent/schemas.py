"""Agent 消息与 API 数据结构。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RunTask(BaseModel):
    """入队任务 — API 写入，Worker 消费。"""

    v: int = 1
    run_id: str
    session_id: str
    user_id: str = "anonymous"
    tenant_id: str = "default"
    message: str
    model: str | None = None
    trace_id: str | None = None
    context: dict[str, Any] | None = None


class AgentEvent(BaseModel):
    """Redis Stream 单条事件。"""

    v: int = 1
    type: str
    run_id: str
    session_id: str = ""
    timestamp: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
