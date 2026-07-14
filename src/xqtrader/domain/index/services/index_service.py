"""指数查询服务 — 基于已采集的 Index / IndexDaily 表提供只读查询。"""

from __future__ import annotations

from datetime import date
from typing import Any

from framework.commons.exceptions import NotFoundException
from framework.commons.pagination import build_paginated_response, paginate
from xqtrader.domain.index.models.index import Index
from xqtrader.domain.index.models.index_daily import IndexDaily
from xqtrader.domain.market.intraday.indicator_calculator import IndicatorCalculator
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
        # 统一使用 IndicatorCalculator 计算技术指标，与个股 K 线口径一致
        bars = [
            {
                "open": r.open or 0.0, "high": r.high or 0.0,
                "low": r.low or 0.0, "close": r.close or 0.0,
                "volume": float(r.vol or 0.0), "amount": float(r.amount or 0.0),
            }
            for r in rows
        ]
        calc = IndicatorCalculator.from_dicts(bars)
        dif, dea, macd = calc.calc_macd(12, 26, 9)
        kdj = calc.calc_kdj(9, 3, 3)
        return {
            "ma": {f"ma{p}": calc.calc_ma(p) for p in [5, 10, 20, 60]},
            "macd": {"dif": dif, "dea": dea, "macd": macd},
            "rsi": {"rsi14": calc.calc_rsi(14)},
            "kdj": kdj,
            "bias": {"bias6": calc.calc_bias(6)},
        }
