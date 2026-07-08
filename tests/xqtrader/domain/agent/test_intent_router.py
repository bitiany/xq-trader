"""Intent Router 单元测试。"""

from __future__ import annotations

import pytest

from xqtrader.domain.agent.intent_router import AgentRoute, IntentRouter, WorkflowRoute


def test_resolve_default_agent_route() -> None:
    route = IntentRouter.resolve("分析 603993.SH")
    assert isinstance(route, AgentRoute)


def test_resolve_explicit_flow_id() -> None:
    route = IntentRouter.resolve(
        "触发工作流",
        flow_id="pre_order_execution_flow",
        context={"workflow_inputs": {"symbol": "603993.SH"}},
    )
    assert isinstance(route, WorkflowRoute)
    assert route.flow_id == "pre_order_execution_flow"
    assert route.inputs["symbol"] == "603993.SH"


def test_resolve_message_prefix() -> None:
    route = IntentRouter.resolve("/workflow pre_order_execution_flow")
    assert isinstance(route, WorkflowRoute)
    assert route.flow_id == "pre_order_execution_flow"


def test_resolve_unknown_flow_raises() -> None:
    with pytest.raises(ValueError, match="不存在"):
        IntentRouter.resolve("x", flow_id="nonexistent_flow_xyz")
