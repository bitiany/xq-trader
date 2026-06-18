"""get_stock_fund_flow Tool — 获取个股资金流向数据。"""

from __future__ import annotations

import json
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters

from agent.tools._http import api_get


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "股票代码，如 600519.SH 或 000001.SZ",
            },
            "limit": {
                "type": "integer",
                "description": "返回最近N个交易日的资金流向，默认10",
            },
        },
        "required": ["symbol"],
    }
)
class GetStockFundFlowTool(Tool):
    _plugin_discoverable = False
    _scopes = {"core"}
    config_key = ""

    @property
    def name(self) -> str:
        return "get_stock_fund_flow"

    @property
    def description(self) -> str:
        return (
            "获取个股近期资金流向数据，包括主力净流入、超大单/大单/中单/小单的买卖净额，"
            "用于分析主力资金动向和散户行为。数据按交易日倒序返回。"
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        symbol = kwargs.get("symbol", "")
        limit = kwargs.get("limit", 10)
        if not symbol:
            return json.dumps({"error": "symbol 参数不能为空"}, ensure_ascii=False)

        try:
            data = await api_get(
                f"/api/v1/stocks/{symbol}/fund-flow",
                params={"limit": limit},
            )
        except Exception as exc:
            return json.dumps({"error": f"获取资金流向失败: {exc}"}, ensure_ascii=False)

        items = data.get("items", [])
        if not items:
            return json.dumps(
                {"symbol": symbol, "has_data": False, "items": []},
                ensure_ascii=False,
            )

        latest = items[-1] if items else {}
        main_flow_trend = None
        if len(items) >= 2:
            prev_main = items[-2].get("main_net_amt")
            curr_main = latest.get("main_net_amt")
            if prev_main is not None and curr_main is not None:
                if curr_main > prev_main:
                    main_flow_trend = "inflow_increasing"
                elif curr_main < prev_main:
                    main_flow_trend = "inflow_decreasing"
                else:
                    main_flow_trend = "stable"

        result: dict[str, Any] = {
            "symbol": symbol,
            "has_data": True,
            "latest": {
                "trade_date": latest.get("trade_date", ""),
                "main_net_amt": latest.get("main_net_amt"),
                "main_net_pct": latest.get("main_net_pct"),
                "huge_net_amt": latest.get("huge_net_amt"),
                "big_net_amt": latest.get("big_net_amt"),
                "mid_net_amt": latest.get("mid_net_amt"),
                "small_net_amt": latest.get("small_net_amt"),
                "net_mf_amt": latest.get("net_mf_amt"),
            },
            "main_flow_trend": main_flow_trend,
            "recent_items": items,
        }

        return json.dumps(result, ensure_ascii=False, default=str)
