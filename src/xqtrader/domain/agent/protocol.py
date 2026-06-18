"""Agent Redis 协议 — 与 xqtrader-bot/agent/protocol.py 保持同步。"""

from __future__ import annotations

from enum import Enum
from typing import Any

PROTOCOL_VERSION = 1

QUEUE_KEY = "agent:runs:queue"


def run_events_key(run_id: str) -> str:
    return f"agent:run:{run_id}:events"


def run_meta_key(run_id: str) -> str:
    return f"agent:run:{run_id}:meta"


def run_cancel_key(run_id: str) -> str:
    return f"agent:run:{run_id}:cancel"


def session_key(session_id: str) -> str:
    return f"agent:session:{session_id}"


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventType(str, Enum):
    RUN_START = "run_start"
    THINKING = "thinking"
    TOKEN = "token"
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    MESSAGE = "message"
    ERROR = "error"
    DONE = "done"


class MetaField(str, Enum):
    STATUS = "status"
    SESSION_ID = "session_id"
    USER_ID = "user_id"
    TENANT_ID = "tenant_id"
    TRACE_ID = "trace_id"
    ERROR = "error"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


def sse_event_name(event_type: EventType | str) -> str:
    return str(event_type.value if isinstance(event_type, EventType) else event_type)


def build_stream_fields(
    event_type: EventType | str,
    run_id: str,
    *,
    session_id: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, str]:
    import json
    from datetime import datetime, timezone

    body: dict[str, Any] = {
        "v": PROTOCOL_VERSION,
        "type": str(event_type.value if isinstance(event_type, EventType) else event_type),
        "run_id": run_id,
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload or {},
    }
    return {"data": json.dumps(body, ensure_ascii=False)}
