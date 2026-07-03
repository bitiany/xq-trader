"""Agent Worker 数据结构 — 统一使用 xqtrader.domain.agent.schemas 定义，避免重复。"""

from xqtrader.domain.agent.schemas import (
    AgentEventPayload as AgentEvent,
)
from xqtrader.domain.agent.schemas import (
    RunTask,
)

__all__ = ["AgentEvent", "RunTask"]
