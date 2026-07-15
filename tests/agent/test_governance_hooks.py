"""Orchestrator 工具策略单元测试。"""

from __future__ import annotations

import pytest

from agent.governance_hooks import (
    OrchestratorToolPolicyHook,
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
    from nanobot.providers.base import LLMResponse, ToolCallRequest

    hook = OrchestratorToolPolicyHook({"skill": "stock-research"})
    tc = ToolCallRequest(
        id="1",
        name="mcp_xq_stocks_xq_get_stock_fund_flow",
        arguments={"symbol": "603993.SH"},
    )
    context = AgentHookContext(
        iteration=1,
        messages=[],
        response=LLMResponse(
            content="",
            tool_calls=[tc],
            finish_reason="tool_calls",
            usage={},
        ),
        tool_calls=[tc],
    )
    await hook.before_execute_tools(context)
    assert tc.name == "_blocked_by_policy"
    assert tc.arguments["blocked_tool"] == "get_stock_fund_flow"
    assert "禁止直接调用" in tc.arguments["reason"]


@pytest.mark.asyncio
async def test_tool_policy_allows_spawn() -> None:
    from nanobot.agent.hook import AgentHookContext
    from nanobot.providers.base import LLMResponse, ToolCallRequest

    hook = OrchestratorToolPolicyHook({"skill": "stock-research"})
    tc = ToolCallRequest(
        id="1",
        name="spawn",
        arguments={"task": "[spawn-worker:technical] test"},
    )
    context = AgentHookContext(
        iteration=1,
        messages=[],
        response=LLMResponse(
            content="",
            tool_calls=[tc],
            finish_reason="tool_calls",
            usage={},
        ),
        tool_calls=[tc],
    )
    await hook.before_execute_tools(context)
    assert tc.name == "spawn"
