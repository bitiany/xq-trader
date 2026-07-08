"""个股实时行情 SPI（前缀匹配，单例 job 批量处理多 symbol）"""

from __future__ import annotations

from typing import Any

from framework.ws.exceptions import WsSpiError
from xqtrader.domain.market.services.local_market_quote_service import LocalMarketQuoteService
from xqtrader.ws.constants import WsTopic

from .. import PrefixTopicSpi, register_prefix_spi


@register_prefix_spi
class StockQuoteSpi(PrefixTopicSpi):
    """个股行情 SPI — 从本地 CandlestickDaily 读取最新日线行情。"""

    @property
    def topic_prefix(self) -> str:
        return WsTopic.MARKET_STOCK_QUOTE_PREFIX

    def execute_for_topics(self, topics: list[str]) -> dict[str, Any]:
        raise WsSpiError("StockQuoteSpi 仅支持 execute_for_topics_async")

    async def execute_for_topics_async(self, topics: list[str]) -> dict[str, Any]:
        prefix = WsTopic.MARKET_STOCK_QUOTE_PREFIX
        symbol_to_topic: dict[str, str] = {}
        for topic in topics:
            symbol = topic[len(prefix):]
            if symbol:
                symbol_to_topic[symbol] = topic

        if not symbol_to_topic:
            return {}

        latest_rows = await LocalMarketQuoteService.fetch_latest_daily_rows(list(symbol_to_topic.keys()))
        results: dict[str, Any] = {}
        for symbol, topic in symbol_to_topic.items():
            results[topic] = LocalMarketQuoteService.build_stock_snapshot(
                symbol,
                latest_rows.get(symbol),
            )
        return results
