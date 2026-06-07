"""WebSocket消息模型与统一常量"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

# ── 统一常量 ──
CHANNEL_PREFIX = "ws:topic:"
SUBSCRIBERS_PREFIX = "ws:topic:"
TICKET_PREFIX = "ws:ticket:"


class WsClientMethod(str, Enum):
    SUBSCRIBE = "SUBSCRIBE"
    UNSUBSCRIBE = "UNSUBSCRIBE"
    PING = "PING"
    LIST_SUBSCRIPTIONS = "LIST_SUBSCRIPTIONS"


class WsClientMessage(BaseModel):
    method: WsClientMethod
    params: Any = Field(default_factory=list)
    id: int | str | None = None


class WsServerMessageType(str, Enum):
    SNAPSHOT = "SNAPSHOT"
    UPDATE = "UPDATE"
    ACK = "ACK"
    PING = "PING"
    PONG = "PONG"
    RESULT = "RESULT"
    ERROR = "ERROR"


class WsServerMessage(BaseModel):
    type: WsServerMessageType
    channel: str | None = None
    data: Any = None
    id: int | str | None = None
    code: str | None = None
    message: str | None = None
