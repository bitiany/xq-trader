"""get_stock_financials Tool — 获取个股财务数据。"""

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
class GetStockFinancialsTool(Tool):
    _plugin_discoverable = False
    _scopes = {"core"}
    config_key = ""

    @property
    def name(self) -> str:
        return "get_stock_financials"

    @property
    def description(self) -> str:
        return "获取个股最新财务数据，包括利润表、资产负债表、现金流量表和关键财务指标的摘要"

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        symbol = kwargs.get("symbol", "")
        if not symbol:
            return json.dumps({"error": "symbol 参数不能为空"}, ensure_ascii=False)
        try:
            data = await api_get(f"/api/v1/stocks/{symbol}/financials")
            result = {
                "symbol": data.get("symbol", symbol),
            }
            for section in ("income_statement", "balance_sheet", "cash_flow", "financial_indicator"):
                raw = data.get(section)
                if raw:
                    result[section] = {
                        "end_date": raw.get("end_date", ""),
                        "ann_date": raw.get("ann_date", ""),
                        "highlights": raw.get("highlights", {}),
                    }
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as exc:
            return json.dumps({"error": f"获取财务数据失败: {exc}"}, ensure_ascii=False)
