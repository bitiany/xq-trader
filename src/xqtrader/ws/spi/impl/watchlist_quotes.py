"""自选股实时行情 SPI"""

from __future__ import annotations

import time
from typing import Any, cast

from framework.commons.logger import get_logger
from framework.commons.redis_client import redis_client
from framework.ws.exceptions import WsSpiError
from xqtrader.broker.services.qmt_data_collector import QmtDataCollector
from xqtrader.ws.constants import WsTopic

from .. import TopicSpi, register_spi

logger = get_logger("ws.spi.watchlist_quotes")

# Redis Key 前缀：按账户存储自选股 symbols
# 格式：trading:watchlist:{account_id}:quote_symbols -> Set[symbol]
WATCHLIST_SYMBOLS_PREFIX = "trading:watchlist"


@register_spi
class WatchlistQuotesSpi(TopicSpi):
    """自选股实时行情 SPI — 从 QMT 全推 Tick 获取最新价格

    按账户维度推送：遍历 Redis 中所有 trading:watchlist:{account_id}:quote_symbols，
    为每个有自选股的账户独立推送行情数据，携带 account_id 字段。
    """

    @property
    def topic_name(self) -> str:
        return WsTopic.MARKET_WATCHLIST_QUOTES

    def execute(self) -> dict:
        try:
            account_symbols = self._load_all_account_symbols()
            if not account_symbols:
                return {"items": [], "timestamp": time.time(), "reason": "empty_watchlist"}

            all_symbols: set[str] = set()
            for symbols in account_symbols.values():
                all_symbols.update(symbols)

            ticks = QmtDataCollector.sync_get_full_tick(list(all_symbols))

            items = []
            for account_id, symbols in account_symbols.items():
                for symbol in symbols:
                    item = self._normalize_tick(symbol, ticks.get(symbol))
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

    @staticmethod
    def _normalize_tick(symbol: str, raw: Any) -> dict:
        if not isinstance(raw, dict):
            return {"symbol": symbol, "last_price": None, "change_pct": None, "timestamp": time.time()}

        raw_last = raw.get("lastPrice")
        if raw_last is None:
            raw_last = raw.get("last_price")
        if raw_last is None:
            raw_last = raw.get("price")
        last = WatchlistQuotesSpi._to_float(raw_last)

        raw_pre_close = raw.get("lastClose")
        if raw_pre_close is None:
            raw_pre_close = raw.get("preClose")
        if raw_pre_close is None:
            raw_pre_close = raw.get("pre_close")
        pre_close = WatchlistQuotesSpi._to_float(raw_pre_close)
        change_pct = None
        if last is not None and pre_close is not None and pre_close != 0:
            change_pct = (last - pre_close) / pre_close * 100

        return {
            "symbol": symbol,
            "last_price": round(last, 4) if last is not None else None,
            "change_pct": round(change_pct, 4) if change_pct is not None else None,
            "timestamp": time.time(),
        }

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        return float(value)
