"""指数查询服务 — 基于已采集的 Index / IndexDaily 表提供只读查询。"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import talib  # type: ignore[import-unfound]

from framework.commons.exceptions import NotFoundException
from framework.commons.pagination import build_paginated_response, paginate
from xqtrader.domain.index.models.index import Index
from xqtrader.domain.index.models.index_daily import IndexDaily
from xqtrader.domain.security.services.stock_detail_service import StockApiFormatter


class IndexService:
    """指数基本信息与概览服务。"""

    async def list_indices(
        self,
        keyword: str | None = None,
        index_type: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        skip, limit = paginate(page, page_size)
        filters: dict[str, Any] = {}
        if keyword:
            filters["name__like"] = f"%{keyword}%"
        if index_type:
            filters["index_type"] = index_type
        rows = await Index.filter(skip=skip, limit=limit, **filters)
        total = await Index.count(**filters)
        items = [
            {
                "index_code": row.index_code,
                "name": row.name,
                "index_type": row.index_type,
                "base_date": row.base_date,
                "base_value": StockApiFormatter.value(row.base_value),
            }
            for row in rows
        ]
        return build_paginated_response(items, total, page, page_size)

    async def get_overview(self, symbol: str) -> dict[str, Any]:
        index = await Index.filter(index_code=symbol, limit=1)
        if not index:
            raise NotFoundException(message=f"指数不存在: {symbol}")
        info = index[0]
        candles = await IndexDaily.filter(
            symbol=symbol, order_by=IndexDaily.trade_date.desc(), limit=1,
        )
        latest = candles[0] if candles else None
        return {
            "symbol": info.index_code,
            "name": info.name,
            "index_type": info.index_type,
            "base_date": info.base_date,
            "base_value": StockApiFormatter.value(info.base_value),
            "quote": self._quote_snapshot(symbol, latest),
            "fund_flow_available": False,
        }

    @staticmethod
    def _quote_snapshot(symbol: str, candle: IndexDaily | None) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "last": StockApiFormatter.value(getattr(candle, "close", None)),
            "prev_close": StockApiFormatter.value(getattr(candle, "pre_close", None)),
            "change": StockApiFormatter.value(getattr(candle, "change", None)),
            "change_pct": StockApiFormatter.value(getattr(candle, "pct_chg", None)),
            "open": StockApiFormatter.value(getattr(candle, "open", None)),
            "high": StockApiFormatter.value(getattr(candle, "high", None)),
            "low": StockApiFormatter.value(getattr(candle, "low", None)),
            "volume": StockApiFormatter.value(getattr(candle, "vol", None)),
            "amount": StockApiFormatter.value(getattr(candle, "amount", None)),
            "timestamp": StockApiFormatter.date_value(getattr(candle, "trade_date", None)),
            "status": "closed",
            "source": "daily",
        }


class IndexKlineService:
    """指数K线及技术指标服务。"""

    async def get_kline(self, symbol: str, limit: int = 1200) -> dict[str, Any]:
        rows = await IndexDaily.filter(
            symbol=symbol, order_by=IndexDaily.trade_date.desc(), limit=limit,
        )
        if not rows:
            raise NotFoundException(message=f"指数K线数据不存在: {symbol}")
        rows = list(reversed(rows))
        bars = [self._bar_item(row) for row in rows]
        overlays = self._technical_overlays(rows)
        return {
            "symbol": symbol,
            "bars": bars,
            "overlays": overlays,
            "ma_overlays": overlays["ma"],
        }

    @staticmethod
    def _bar_item(row: IndexDaily) -> dict[str, Any]:
        return {
            "trade_date": row.trade_date.isoformat() if isinstance(row.trade_date, date) else row.trade_date,
            "open": StockApiFormatter.value(row.open),
            "close": StockApiFormatter.value(row.close),
            "high": StockApiFormatter.value(row.high),
            "low": StockApiFormatter.value(row.low),
            "volume": StockApiFormatter.value(row.vol),
            "amount": StockApiFormatter.value(row.amount),
            "pct_chg": StockApiFormatter.value(row.pct_chg),
        }

    @staticmethod
    def _technical_overlays(
        rows: list[IndexDaily],
    ) -> dict[str, dict[str, list[float | None]]]:
        if not rows:
            return {key: {} for key in ["ma", "macd", "rsi", "kdj", "bias"]}
        close = np.array([row.close for row in rows], dtype=float)
        high = np.array([row.high for row in rows], dtype=float)
        low = np.array([row.low for row in rows], dtype=float)
        ma = {f"ma{p}": StockApiFormatter.series(talib.MA(close, timeperiod=p)) for p in [5, 10, 20, 60]}
        dif, dea, macd = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
        k, d = talib.STOCH(high, low, close, fastk_period=9, slowk_period=3, slowd_period=3)
        j = 3 * k - 2 * d
        ma_arr = talib.MA(close, timeperiod=6)
        bias = ((close - ma_arr) / ma_arr) * 100
        return {
            "ma": ma,
            "macd": {
                "dif": StockApiFormatter.series(dif),
                "dea": StockApiFormatter.series(dea),
                "macd": StockApiFormatter.series(macd * 2),
            },
            "rsi": {"rsi14": StockApiFormatter.series(talib.RSI(close, timeperiod=14))},
            "kdj": {
                "k": StockApiFormatter.series(k),
                "d": StockApiFormatter.series(d),
                "j": StockApiFormatter.series(j),
            },
            "bias": {"bias6": StockApiFormatter.series(bias)},
        }
