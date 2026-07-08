"""本地行情读取服务 — 从已采集的 CandlestickDaily 表提供行情快照。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import desc

from xqtrader.domain.market.models.candlestick import CandlestickDaily


class LocalMarketQuoteService:
    """读取本地日线行情，供 WebSocket / API 展示使用。"""

    @classmethod
    async def fetch_latest_daily_rows(cls, symbols: list[str]) -> dict[str, CandlestickDaily]:
        if not symbols:
            return {}
        unique_symbols = list(dict.fromkeys(symbols))
        rows = await CandlestickDaily.filter(
            symbol__in=unique_symbols,
            limit=None,
            order_by=desc(CandlestickDaily.trade_date),
        )
        latest: dict[str, CandlestickDaily] = {}
        for row in rows:
            if row.symbol not in latest:
                latest[row.symbol] = row
        return latest

    @classmethod
    async def fetch_daily_kline(
        cls,
        symbols: list[str],
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> dict[str, list[CandlestickDaily]]:
        if not symbols:
            return {}
        filters: dict[str, Any] = {"symbol__in": list(dict.fromkeys(symbols)), "limit": None}
        if start_date is not None:
            filters["trade_date__gte"] = start_date
        if end_date is not None:
            filters["trade_date__lte"] = end_date
        rows = await CandlestickDaily.filter(
            order_by=[CandlestickDaily.symbol, CandlestickDaily.trade_date],
            **filters,
        )
        grouped: dict[str, list[CandlestickDaily]] = {symbol: [] for symbol in symbols}
        for row in rows:
            grouped.setdefault(row.symbol, []).append(row)
        return grouped

    @classmethod
    def build_watchlist_quote(cls, symbol: str, row: CandlestickDaily | None) -> dict[str, Any]:
        if row is None:
            return {"symbol": symbol, "last_price": None, "change_pct": None, "timestamp": datetime.now().timestamp()}
        last = float(row.close)
        change_pct = float(row.pct_chg) if row.pct_chg is not None else None
        if change_pct is None and row.pre_close not in (None, 0):
            change_pct = (last - float(row.pre_close)) / float(row.pre_close) * 100
        return {
            "symbol": symbol,
            "last_price": round(last, 4),
            "change_pct": round(change_pct, 4) if change_pct is not None else None,
            "trade_date": row.trade_date.isoformat(),
            "timestamp": datetime.now().timestamp(),
            "source": "local_daily",
        }

    @classmethod
    def build_stock_snapshot(cls, symbol: str, row: CandlestickDaily | None) -> dict[str, Any]:
        if row is None:
            return cls._empty_snapshot(symbol)
        last = float(row.close)
        prev_close = float(row.pre_close) if row.pre_close is not None else None
        change = float(row.change) if row.change is not None else None
        change_pct = float(row.pct_chg) if row.pct_chg is not None else None
        if change is None and prev_close is not None:
            change = round(last - prev_close, 4)
        if change_pct is None and prev_close not in (None, 0):
            change_pct = round((last - prev_close) / prev_close * 100, 4)
        return {
            "symbol": symbol,
            "last": last,
            "prev_close": prev_close,
            "change": change,
            "change_pct": change_pct,
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "volume": int(row.volume),
            "amount": float(row.amount),
            "trade_date": row.trade_date.isoformat(),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "closed",
            "source": "local_daily",
        }

    @staticmethod
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
            "trade_date": None,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "closed",
            "source": "local_daily",
        }

    @classmethod
    def serialize_kline_rows(cls, rows: list[CandlestickDaily]) -> dict[str, Any]:
        if not rows:
            return {"count": 0, "columns": [], "data": []}
        columns = [
            "trade_date", "open", "close", "high", "low",
            "volume", "amount", "change", "pre_close", "pct_chg", "data_source",
        ]
        data = [
            [
                row.trade_date.isoformat(),
                row.open,
                row.close,
                row.high,
                row.low,
                row.volume,
                row.amount,
                row.change,
                row.pre_close,
                row.pct_chg,
                row.data_source,
            ]
            for row in rows
        ]
        return {"count": len(rows), "columns": columns, "data": data}
