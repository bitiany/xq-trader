"""Intent Router — submit_message 入口分流 Agent Loop / FlowEngine。"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from framework.config.settings import settings

_FLOW_PREFIX_RE = re.compile(r"^/(?:workflow|flow)\s+([a-zA-Z0-9_-]+)\s*$")
_FLOW_HASH_RE = re.compile(r"^#flow:([a-zA-Z0-9_-]+)\s*$")


@dataclass(frozen=True, slots=True)
class AgentRoute:
    """走 Agent Worker 队列。"""


@dataclass(frozen=True, slots=True)
class WorkflowRoute:
    """走 FlowEngine 同步执行。"""

    flow_id: str
    inputs: dict[str, Any]


class IntentRouter:
    """按显式 flow_id 或消息前缀将请求分流到工作流或 Agent。"""

    @staticmethod
    def flow_config_path(flow_id: str) -> str:
        return os.path.join(settings.APP.ROOT_DIR, f"flow/{flow_id}.json")

    @classmethod
    def flow_exists(cls, flow_id: str) -> bool:
        return os.path.isfile(cls.flow_config_path(flow_id))

    @classmethod
    def resolve(
        cls,
        message: str,
        *,
        flow_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> AgentRoute | WorkflowRoute:
        ctx = context or {}
        explicit = (flow_id or str(ctx.get("flow_id") or "")).strip()
        if explicit:
            if not cls.flow_exists(explicit):
                raise ValueError(f"工作流 '{explicit}' 不存在")
            return WorkflowRoute(
                flow_id=explicit,
                inputs=cls._build_workflow_inputs(message, ctx),
            )

        stripped = message.strip()
        for pattern in (_FLOW_PREFIX_RE, _FLOW_HASH_RE):
            match = pattern.match(stripped)
            if match:
                resolved_id = match.group(1)
                if not cls.flow_exists(resolved_id):
                    raise ValueError(f"工作流 '{resolved_id}' 不存在")
                return WorkflowRoute(
                    flow_id=resolved_id,
                    inputs=cls._build_workflow_inputs(stripped, ctx),
                )

        return AgentRoute()

    @staticmethod
    def _build_workflow_inputs(message: str, context: dict[str, Any]) -> dict[str, Any]:
        raw_inputs = context.get("workflow_inputs")
        if isinstance(raw_inputs, dict):
            return dict(raw_inputs)
        if isinstance(raw_inputs, str):
            try:
                parsed = json.loads(raw_inputs)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        inputs: dict[str, Any] = {"message": message}
        for key in ("symbol", "stock_symbol", "workspace_id"):
            if key in context and context[key] not in (None, ""):
                inputs[key] = context[key]
        return inputs
