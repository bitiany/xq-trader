"""get_stock_technicals Tool — 获取个股技术面数据（K线 + 技术指标）。"""

from __future__ import annotations

import json
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters

from agent.tools._http import api_get


async def _fetch_kline_with_indicators(symbol: str) -> dict[str, Any]:
    data = await api_get(
        f"/api/v1/stocks/{symbol}/kline",
        params={"limit": 60},
    )
    return data


async def _fetch_turnover_rate(symbol: str) -> float | None:
    try:
        data = await api_get(f"/api/v1/stocks/{symbol}")
        return float(data.get("valuation", {}).get("turnover_rate"))  # type: ignore[arg-type]
    except Exception:
        return None


def _format_indicator_summary(overlay: dict[str, list[float | None]], bars_count: int) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key, values in overlay.items():
        if not isinstance(values, list) or len(values) == 0:
            summary[key] = {"latest": None, "trend": "no_data"}
            continue
        latest = values[-1] if values else None
        prev = values[-2] if len(values) >= 2 else None
        if latest is not None and prev is not None:
            trend = "up" if latest > prev else "down" if latest < prev else "flat"
        else:
            trend = "no_data"
        summary[key] = {"latest": latest, "trend": trend}
    return summary


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
class GetStockTechnicalsTool(Tool):
    _plugin_discoverable = False
    _scopes = {"core"}
    config_key = ""

    @property
    def name(self) -> str:
        return "get_stock_technicals"

    @property
    def description(self) -> str:
        return (
            "获取个股技术面数据，包括近期K线走势、MA均线、MACD、KDJ、RSI、BIAS等技术指标，"
            "以及换手率等交易指标。数据来源于因子库计算结果。"
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        symbol = kwargs.get("symbol", "")
        if not symbol:
            return json.dumps({"error": "symbol 参数不能为空"}, ensure_ascii=False)

        try:
            data = await _fetch_kline_with_indicators(symbol)
        except Exception as exc:
            return json.dumps({"error": f"获取技术面数据失败: {exc}"}, ensure_ascii=False)

        bars = data.get("bars", [])
        recent_bars = bars[-30:] if len(bars) > 30 else bars
        bars_count = len(bars)

        overlays = data.get("overlays", {})
        ma_overlays = data.get("ma_overlays", {})

        indicator_summary: dict[str, Any] = {}
        for ind_name in ("ma", "macd", "kdj", "rsi", "bias"):
            overlay = overlays.get(ind_name, {})
            if overlay:
                indicator_summary[ind_name] = _format_indicator_summary(overlay, bars_count)

        if ma_overlays:
            indicator_summary["ma_trend"] = _format_indicator_summary(ma_overlays, bars_count)

        turnover_rate = await _fetch_turnover_rate(symbol)

        result: dict[str, Any] = {
            "symbol": symbol,
            "recent_bars": recent_bars,
            "indicators": indicator_summary,
            "turnover_rate": turnover_rate,
        }

        return json.dumps(result, ensure_ascii=False, default=str)
