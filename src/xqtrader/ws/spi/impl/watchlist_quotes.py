"""自选股实时行情 SPI"""

from __future__ import annotations

import time
from typing import Any, cast

from framework.commons.logger import get_logger
from framework.commons.redis_client import redis_client
from framework.ws.exceptions import WsSpiError
from xqtrader.domain.market.services.local_market_quote_service import LocalMarketQuoteService
from xqtrader.ws.constants import WsTopic

from .. import TopicSpi, register_spi

logger = get_logger("ws.spi.watchlist_quotes")

# Redis Key 前缀：按账户存储自选股 symbols
# 格式：trading:watchlist:{account_id}:quote_symbols -> Set[symbol]
WATCHLIST_SYMBOLS_PREFIX = "trading:watchlist"


@register_spi
class WatchlistQuotesSpi(TopicSpi):
    """自选股行情 SPI — 从本地 CandlestickDaily 读取最新日线行情。"""

    @property
    def topic_name(self) -> str:
        return WsTopic.MARKET_WATCHLIST_QUOTES

    def execute(self) -> dict:
        raise WsSpiError("WatchlistQuotesSpi 仅支持 execute_async")

    async def execute_async(self) -> dict:
        try:
            account_symbols = self._load_all_account_symbols()
            if not account_symbols:
                return {"items": [], "timestamp": time.time(), "reason": "empty_watchlist"}

            all_symbols: set[str] = set()
            for symbols in account_symbols.values():
                all_symbols.update(symbols)

            latest_rows = await LocalMarketQuoteService.fetch_latest_daily_rows(list(all_symbols))

            items = []
            for account_id, symbols in account_symbols.items():
                for symbol in symbols:
                    item = LocalMarketQuoteService.build_watchlist_quote(
                        symbol,
                        latest_rows.get(symbol),
                    )
                    item["account_id"] = account_id
                    items.append(item)

            return {
                "items": items,
                "timestamp": time.time(),
            }
        except WsSpiError:
            raise
        except Exception as e:
            raise WsSpiError("Watchlist quote query failed") from e

    @staticmethod
    def _load_all_account_symbols() -> dict[int, list[str]]:
        """从 Redis 加载所有账户的自选股 symbols，返回 {account_id: [symbol, ...]}"""
        result: dict[int, list[str]] = {}
        pattern = f"{WATCHLIST_SYMBOLS_PREFIX}:*:quote_symbols"
        cursor: int = 0
        while True:
            cursor, keys = redis_client.scan(cursor, match=pattern, count=100)
            for key in keys:
                if isinstance(key, bytes):
                    key = key.decode()
                parts = key.split(":")
                if len(parts) >= 3:
                    try:
                        account_id = int(parts[2])
                    except (ValueError, IndexError):
                        continue
                    values = cast(set[Any], redis_client.smembers(key))
                    symbols: list[str] = []
                    for value in values:
                        if isinstance(value, bytes):
                            symbols.append(value.decode())
                        else:
                            symbols.append(cast(str, value))
                    if symbols:
                        result[account_id] = sorted(symbols)
            if cursor == 0:
                break
        return result
