"""get_stock_overview Tool — 获取个股概览、行情快照与估值。"""

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
        },
        "required": ["symbol"],
    }
)
class GetStockOverviewTool(Tool):
    _plugin_discoverable = False
    _scopes = {"core"}
    config_key = ""

    @property
    def name(self) -> str:
        return "get_stock_overview"

    @property
    def description(self) -> str:
        return (
            "获取个股概览信息，包括公司名称、行业、行情快照"
            "（最新价/涨跌幅/成交量等）、估值指标（PE/PB/PS/市值等）和公司简介"
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        symbol = kwargs.get("symbol", "")
        if not symbol:
            return json.dumps({"error": "symbol 参数不能为空"}, ensure_ascii=False)
        try:
            data = await api_get(f"/api/v1/stocks/{symbol}")
            quote = data.get("quote", {})
            valuation = data.get("valuation", {})
            result = {
                "symbol": data.get("symbol", symbol),
                "name": data.get("name", ""),
                "industry": data.get("industry", ""),
                "market": data.get("market", ""),
                "exchange": data.get("exchange", ""),
                "introduction": data.get("introduction", ""),
                "quote": {
                    "last": quote.get("last"),
                    "prev_close": quote.get("prev_close"),
                    "change": quote.get("change"),
                    "change_pct": quote.get("change_pct"),
                    "open": quote.get("open"),
                    "high": quote.get("high"),
                    "low": quote.get("low"),
                    "volume": quote.get("volume"),
                    "amount": quote.get("amount"),
                    "timestamp": quote.get("timestamp", ""),
                },
                "valuation": {
                    "trade_date": valuation.get("trade_date", ""),
                    "close": valuation.get("close"),
                    "pe": valuation.get("pe"),
                    "pe_ttm": valuation.get("pe_ttm"),
                    "pb": valuation.get("pb"),
                    "ps": valuation.get("ps"),
                    "ps_ttm": valuation.get("ps_ttm"),
                    "dv_ratio": valuation.get("dv_ratio"),
                    "total_mv": valuation.get("total_mv"),
                    "circ_mv": valuation.get("circ_mv"),
                    "turnover_rate": valuation.get("turnover_rate"),
                },
                "tags": [
                    {"key": t.get("key", ""), "label": t.get("label", "")}
                    for t in data.get("tags", [])
                ],
            }
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as exc:
            return json.dumps({"error": f"获取个股概览失败: {exc}"}, ensure_ascii=False)
