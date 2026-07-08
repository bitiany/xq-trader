"""Orchestrator 工具策略单元测试。"""

from __future__ import annotations

import pytest

from agent.governance_hooks import (
    OrchestratorToolPolicyHook,
    ToolPolicyViolationError,
    _match_forbidden_operation,
    _stock_research_policy_enabled,
)


def test_policy_enabled_for_stock_research_skill() -> None:
    assert _stock_research_policy_enabled({"skill": "stock-research"}) is True
    assert _stock_research_policy_enabled({"skill": "fund-flow"}) is False


def test_match_forbidden_operation() -> None:
    assert _match_forbidden_operation("mcp_xq_stocks_xq_get_stock_fund_flow") == (
        "get_stock_fund_flow"
    )


@pytest.mark.asyncio
async def test_tool_policy_blocks_fund_flow_for_orchestrator() -> None:
    from nanobot.agent.hook import AgentHookContext
    from nanobot.providers.base import ToolCallRequest

    hook = OrchestratorToolPolicyHook({"skill": "stock-research"})
    context = AgentHookContext(
        iteration=1,
        messages=[],
        tool_calls=[
            ToolCallRequest(
                id="1",
                name="mcp_xq_stocks_xq_get_stock_fund_flow",
                arguments={"symbol": "603993.SH"},
            ),
        ],
    )
    with pytest.raises(ToolPolicyViolationError, match="禁止调用"):
        await hook.before_execute_tools(context)
