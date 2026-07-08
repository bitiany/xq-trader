"""MCP 响应 DSL 单元测试。"""

from __future__ import annotations

import textwrap

import pytest

from mcp_server.config import GroupSection, InvokeOverride, ResponseTransform, ToolOverride
from mcp_server.openapi.operation import Operation, Parameter
from mcp_server.response.transformer import ResponseTransformer, TransformError
from mcp_server.schema.mapper import build_input_schema
from mcp_server.server.factory import _merge_invoke_arguments

_FUND_FLOW_SAMPLE = {
    "symbol": "603993.SH",
    "items": [
        {
            "trade_date": "2026-07-02",
            "close": 18.29,
            "main_net_amt": 22837.99,
            "main_net_pct": 2.87,
            "huge_net_amt": 35294.51,
            "huge_net_pct": 4.44,
            "big_net_amt": -12456.52,
            "big_net_pct": -1.57,
            "huge_net_inflow_pct": 1.9145,
            "big_net_inflow_pct": -3.7722,
        },
        {
            "trade_date": "2026-07-03",
            "close": 18.52,
            "main_net_amt": 29079.35,
            "main_net_pct": 4.16,
            "huge_net_amt": 22780.85,
            "huge_net_pct": 3.26,
            "big_net_amt": 6298.5,
            "big_net_pct": 0.9,
            "huge_net_inflow_pct": 3.6246,
            "big_net_inflow_pct": -1.8656,
        },
        {
            "trade_date": "2026-07-06",
            "close": 18.31,
            "main_net_amt": -10174.92,
            "main_net_pct": -1.8,
            "huge_net_amt": -20059.2,
            "huge_net_pct": -3.56,
            "big_net_amt": 9884.28,
            "big_net_pct": 1.75,
            "huge_net_inflow_pct": 0.325,
            "big_net_inflow_pct": -0.2132,
        },
    ],
}

_FUND_FLOW_JMESPATH = textwrap.dedent(
    """
    {
      "标的代码": symbol,
      "最新一日": items[-1].{
        "交易日期": trade_date,
        "收盘价": close,
        "主力净流入额_万元": main_net_amt,
        "主力净流入占比_百分比": main_net_pct,
        "超大单净流入额_万元": huge_net_amt,
        "超大单净流入占比_百分比": huge_net_pct,
        "大单净流入额_万元": big_net_amt,
        "大单净流入占比_百分比": big_net_pct
      },
      "近5日主力占比趋势": items[-5:].{
        "交易日期": trade_date,
        "主力净流入占比_百分比": main_net_pct,
        "超大单净流入占比_百分比": huge_net_pct,
        "大单净流入占比_百分比": big_net_pct
      }
    }
    """
).strip()


def test_fund_flow_transform_latest_day_sign() -> None:
    view = ResponseTransformer.transform(_FUND_FLOW_SAMPLE, _FUND_FLOW_JMESPATH)
    latest = view["最新一日"]
    assert latest["交易日期"] == "2026-07-06"
    assert latest["主力净流入占比_百分比"] == -1.8
    assert latest["主力净流入额_万元"] == -10174.92
    assert "huge_net_inflow_pct" not in latest
    assert "big_net_inflow_pct" not in latest


def test_fund_flow_transform_recent_trend_length() -> None:
    view = ResponseTransformer.transform(_FUND_FLOW_SAMPLE, _FUND_FLOW_JMESPATH)
    trend = view["近5日主力占比趋势"]
    assert len(trend) == 3
    assert trend[-1]["主力净流入占比_百分比"] == -1.8


def test_transform_invalid_jmespath_raises() -> None:
    with pytest.raises(TransformError):
        ResponseTransformer.transform({"a": 1}, "invalid[[[")


def test_merge_invoke_defaults_fill_missing_only() -> None:
    override = ToolOverride(invoke=InvokeOverride(defaults={"limit": 5}))
    merged = _merge_invoke_arguments({"symbol": "603993.SH"}, override)
    assert merged == {"symbol": "603993.SH", "limit": 5}
    merged2 = _merge_invoke_arguments({"limit": 10}, override)
    assert merged2["limit"] == 10


def test_build_input_schema_hides_params() -> None:
    op = Operation(
        operation_id="get_stock_fund_flow",
        method="GET",
        path="/api/v1/stocks/{symbol}/fund-flow",
        parameters=[
            Parameter(
                name="symbol",
                location="path",
                required=True,
                schema={"type": "string"},
            ),
            Parameter(
                name="limit",
                location="query",
                required=False,
                schema={"type": "integer"},
            ),
        ],
    )
    schema = build_input_schema(op, hide_params=["limit"])
    assert "symbol" in schema["properties"]
    assert "limit" not in schema["properties"]
    assert schema.get("additionalProperties") is False


def test_group_section_tools_config_loads() -> None:
    section = GroupSection(
        title="t",
        tools={
            "get_stock_fund_flow": ToolOverride(
                response=ResponseTransform(jmespath='{"x": symbol}'),
            ),
        },
    )
    assert section.tools["get_stock_fund_flow"].response is not None
