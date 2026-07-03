"""个股因子宽表时序服务 — 平台活跃因子一次性返回，按 trade_date 宽字段展开。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from framework.commons.exceptions import NotFoundException
from framework.commons.logger import get_logger
from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry
from xqtrader.domain.factor.models.factor_stats import FacFactorStats
from xqtrader.domain.factor.services import factor_data_loader as fdl
from xqtrader.domain.market.models.candlestick import CandlestickDaily

logger = get_logger("FACTOR_SERIES")

_DEFAULT_LOOKBACK_DAYS = 120
_MAX_LOOKBACK_DAYS = 504


class FactorSeriesService:
    """加载平台活跃因子元数据及单标的宽表时序。"""

    async def get_stock_factor_series(
        self,
        symbol: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        pool_id: str = "all",
    ) -> dict[str, Any]:
        await self._ensure_symbol(symbol)
        end = end_date or date.today()
        start = start_date or (end - timedelta(days=int(_DEFAULT_LOOKBACK_DAYS * 1.6)))
        if (end - start).days > _MAX_LOOKBACK_DAYS:
            start = end - timedelta(days=_MAX_LOOKBACK_DAYS)

        registry_items = await FacFactorRegistry.filter(
            status="active",
            order_by=FacFactorRegistry.factor_id,
            limit=0,
        )
        if not registry_items:
            return self._empty_payload(symbol, pool_id, start, end, [])

        factor_ids = [r.factor_id for r in registry_items]
        factors_meta = [await self._factor_meta(r) for r in registry_items]

        wide_df = await self._load_wide_panel(symbol, factor_ids, start, end, pool_id)
        rows = self._to_wide_rows(wide_df, factor_ids)

        return {
            "symbol": symbol,
            "pool_id": pool_id,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "factor_count": len(factor_ids),
            "factors": factors_meta,
            "columns": ["trade_date", *factor_ids],
            "rows": rows,
        }

    async def _ensure_symbol(self, symbol: str) -> None:
        rows = await CandlestickDaily.filter(symbol=symbol, limit=1)
        if not rows:
            raise NotFoundException(message=f"标的不存在或无行情: {symbol}")

    async def _factor_meta(self, reg: FacFactorRegistry) -> dict[str, Any]:
        stats_rows = await FacFactorStats.filter(
            factor_id=reg.factor_id,
            pool_id="all",
            order_by=FacFactorStats.calc_date.desc(),
            limit=1,
        )
        latest_stats = stats_rows[0].to_dict() if stats_rows else None
        return {
            "factor_id": reg.factor_id,
            "display_name": reg.display_name,
            "category": reg.category,
            "direction": reg.direction,
            "signal_type": reg.signal_type,
            "data_origin": reg.data_origin,
            "factor_grade": reg.factor_grade,
            "is_composite": bool(reg.is_composite),
            "composite_method": reg.composite_method,
            "description": reg.description,
            "latest_stats": latest_stats,
        }

    async def _load_wide_panel(
        self,
        symbol: str,
        factor_ids: list[str],
        start_date: date,
        end_date: date,
        pool_id: str,
    ) -> pd.DataFrame:
        stored = await fdl.load_from_factor_value(
            start_date, end_date, factor_ids, [symbol], pool_id,
        )
        if stored.empty:
            wide = pd.DataFrame()
        elif symbol in stored.index.get_level_values("symbol"):
            sliced = stored.xs(symbol, level="symbol")
            wide = sliced.to_frame().copy() if isinstance(sliced, pd.Series) else sliced.copy()
        else:
            wide = pd.DataFrame()

        present = set(wide.columns) if not wide.empty else set()
        missing = [fid for fid in factor_ids if fid not in present]
        for factor_id in missing:
            try:
                chunk = await fdl.load_factor_raw_chunk(
                    start_date, end_date, factor_id, [symbol], pool_id,
                )
            except Exception:
                logger.exception("Failed to load factor chunk: %s %s", symbol, factor_id)
                continue
            if chunk.empty or symbol not in chunk.index.get_level_values("symbol"):
                continue
            sym_part = chunk.xs(symbol, level="symbol")
            col = factor_id if factor_id in sym_part.columns else sym_part.columns[0]
            series = sym_part[col]
            if wide.empty:
                wide = series.to_frame(name=factor_id)
            else:
                wide = wide.join(series.rename(factor_id), how="outer")

        if not wide.empty:
            wide = wide.sort_index()
        return wide

    @staticmethod
    def _to_wide_rows(wide_df: pd.DataFrame, factor_ids: list[str]) -> list[dict[str, Any]]:
        if wide_df.empty:
            return []
        rows: list[dict[str, Any]] = []
        for trade_date, row in wide_df.iterrows():
            td = trade_date.date() if hasattr(trade_date, "date") else trade_date
            entry: dict[str, Any] = {"trade_date": td.isoformat() if hasattr(td, "isoformat") else str(td)}
            for factor_id in factor_ids:
                val = row[factor_id] if factor_id in row.index else None
                if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
                    entry[factor_id] = None
                else:
                    entry[factor_id] = float(val)
            rows.append(entry)
        return rows

    @staticmethod
    def _empty_payload(
        symbol: str,
        pool_id: str,
        start: date,
        end: date,
        factors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "pool_id": pool_id,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "factor_count": len(factors),
            "factors": factors,
            "columns": ["trade_date"],
            "rows": [],
        }
