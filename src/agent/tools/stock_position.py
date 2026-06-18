"""get_stock_position Tool — 获取个股当前持仓信息。"""

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
class GetStockPositionTool(Tool):
    _plugin_discoverable = False
    _scopes = {"core"}
    config_key = ""

    @property
    def name(self) -> str:
        return "get_stock_position"

    @property
    def description(self) -> str:
        return "查询当前账户中指定股票的持仓信息，包括持仓数量、成本价、最新价、市值、浮动盈亏等。若无持仓则返回空"

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        symbol = kwargs.get("symbol", "")
        if not symbol:
            return json.dumps({"error": "symbol 参数不能为空"}, ensure_ascii=False)
        try:
            data = await api_get("/api/v1/trading/positions")
            items = data if isinstance(data, list) else data.get("items", [])
            matched = [
                item for item in items
                if isinstance(item, dict) and item.get("symbol") == symbol
            ]
            if not matched:
                return json.dumps(
                    {"symbol": symbol, "has_position": False, "position": None},
                    ensure_ascii=False,
                )
            pos = matched[0]
            return json.dumps(
                {
                    "symbol": symbol,
                    "has_position": True,
                    "position": {
                        "name": pos.get("name", ""),
                        "qty": pos.get("qty", 0),
                        "can_use_qty": pos.get("can_use_qty", 0),
                        "cost_price": pos.get("cost_price"),
                        "last_price": pos.get("last_price"),
                        "market_value": pos.get("market_value"),
                        "floating_pnl": pos.get("floating_pnl"),
                        "floating_pnl_pct": pos.get("floating_pnl_pct"),
                        "change_pct": pos.get("change_pct"),
                        "status": pos.get("status", ""),
                    },
                },
                ensure_ascii=False,
                default=str,
            )
        except Exception as exc:
            return json.dumps(
                {"symbol": symbol, "has_position": False, "error": f"查询持仓失败: {exc}"},
                ensure_ascii=False,
            )
