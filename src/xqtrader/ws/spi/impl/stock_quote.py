"""个股实时行情 SPI（前缀匹配，单例 job 批量处理多 symbol）"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from xqtrader.broker.services.qmt_data_collector import QmtDataCollector
from xqtrader.ws.constants import WsTopic

from .. import PrefixTopicSpi, register_prefix_spi


@register_prefix_spi
class StockQuoteSpi(PrefixTopicSpi):
    """个股实时行情 SPI — 从 QMT 全推 Tick 获取单个 symbol 实时行情

    前缀匹配：topic = ws.market.stock_quotes.{symbol}，scheduler 对同一前缀只启动一个单例 job。
    execute_for_topics 批量查询所有被订阅的 symbol，返回 {topic: snapshot}。
    """

    @property
    def topic_prefix(self) -> str:
        return WsTopic.MARKET_STOCK_QUOTE_PREFIX

    def execute_for_topics(self, topics: list[str]) -> dict[str, Any]:
        # 从 topic 解析 symbol：ws.market.stock_quotes.600522.SH -> 600522.SH
        prefix = WsTopic.MARKET_STOCK_QUOTE_PREFIX
        symbol_to_topic: dict[str, str] = {}
        for topic in topics:
            symbol = topic[len(prefix):]
            if symbol:
                symbol_to_topic[symbol] = topic

        if not symbol_to_topic:
            return {}

        symbols = list(symbol_to_topic.keys())
        ticks = QmtDataCollector.sync_get_full_tick(symbols)

        results: dict[str, Any] = {}
        for symbol, topic in symbol_to_topic.items():
            snapshot = self._build_snapshot(symbol, ticks.get(symbol))
            results[topic] = snapshot
        return results

    @staticmethod
    def _build_snapshot(symbol: str, raw: Any) -> dict[str, Any]:
        """从 QMT Tick 构造 StockQuoteSnapshot 结构（与前端 StockQuoteSnapshot 对齐）"""
        if not isinstance(raw, dict):
            return _empty_snapshot(symbol)

        last = _to_float(_first(raw, "lastPrice", "last_price", "price"))
        prev_close = _to_float(_first(raw, "lastClose", "preClose", "pre_close"))
        open_price = _to_float(_first(raw, "open", "Open"))
        high = _to_float(_first(raw, "high", "High"))
        low = _to_float(_first(raw, "low", "Low"))
        volume = _to_float(_first(raw, "volume", "Volume"))
        amount = _to_float(_first(raw, "amount", "Amount"))

        change = None
        change_pct = None
        if last is not None and prev_close is not None:
            change = round(last - prev_close, 4)
            if prev_close != 0:
                change_pct = round((last - prev_close) / prev_close * 100, 4)

        # 盘中 high/low 需与 last 取极值（QMT Tick 的 high/low 可能未实时更新）
        if last is not None:
            if high is not None:
                high = max(high, last)
            else:
                high = last
            if low is not None:
                low = min(low, last)
            else:
                low = last

        return {
            "symbol": symbol,
            "last": last,
            "prev_close": prev_close,
            "change": change,
            "change_pct": change_pct,
            "open": open_price,
            "high": high,
            "low": low,
            "volume": int(volume) if volume is not None else None,
            "amount": amount,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "trading",
            "source": "qmt_tick",
        }


def _empty_snapshot(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "last": None,
        "prev_close": None,
        "change": None,
        "change_pct": None,
        "open": None,
        "high": None,
        "low": None,
        "volume": None,
        "amount": None,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "closed",
        "source": "qmt_tick",
    }


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN check
        return None
    return result
