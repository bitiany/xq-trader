"""Agent API 请求/响应模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from xqtrader.domain.agent.protocol import RunStatus


class CreateSessionRequest(BaseModel):
    title: str | None = None
    model: str | None = None


class SessionResponse(BaseModel):
    session_id: str
    title: str | None = None
    model: str | None = None
    created_at: str


class SubmitMessageRequest(BaseModel):
    content: str = Field(min_length=1)
    model: str | None = None
    context: dict[str, Any] | None = None


class SubmitMessageResponse(BaseModel):
    run_id: str
    session_id: str
    status: RunStatus = RunStatus.QUEUED


class RunStatusResponse(BaseModel):
    run_id: str
    session_id: str
    status: RunStatus
    error: str | None = None


class AgentEventPayload(BaseModel):
    v: int = 1
    type: str
    run_id: str
    session_id: str = ""
    timestamp: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class RunTask(BaseModel):
    v: int = 1
    run_id: str
    session_id: str
    user_id: str = "anonymous"
    tenant_id: str = "default"
    message: str
    model: str | None = None
    trace_id: str | None = None
    context: dict[str, Any] | None = None
