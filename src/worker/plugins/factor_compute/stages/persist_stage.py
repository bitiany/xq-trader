"""持久化阶段 — 将因子值写入 fac_factor_value 表。

策略：
  - 根据 start_date 只持久化增量部分数据（预热期和更早数据仅参与计算不持久化）
  - 窄表格式：每行一个因子值
  - pool_id 默认 "all"
  - 向量化构建行列表，避免逐行 Python 循环
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from framework.commons.logger import get_logger
from framework.pipeline import PipelineContext, Stage, StageResult
from xqtrader.domain.factor.models.factor_value import FacFactorValue

logger = get_logger("factor.persist")

_BATCH_SIZE = 2000


def _parse_cutoff(start_date: str) -> date | None:
    """解析 start_date 作为持久化截断日期。"""
    if not start_date:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            if fmt == "%Y-%m-%d":
                return date.fromisoformat(start_date)
            return date(int(start_date[:4]), int(start_date[4:6]), int(start_date[6:8]))
        except (ValueError, IndexError):
            continue
    return None


class FactorPersistStage(Stage):
    """持久化阶段 — 将因子值写入 fac_factor_value 表。"""

    @property
    def name(self) -> str:
        return "factor_persist"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        symbol: str = item

        if ctx.get("skip_persist"):
            return StageResult.ok(data={"symbol": symbol, "persisted": 0})

        df: pd.DataFrame | None = ctx.get("factor_df")
        if df is None or df.empty:
            return StageResult.ok(data={"symbol": symbol, "persisted": 0})

        factor_cols = [c for c in df.columns if c not in ("symbol", "trade_date")]
        if not factor_cols:
            return StageResult.ok(data={"symbol": symbol, "persisted": 0})

        # 根据 start_date 截断：只持久化增量部分，预热期数据仅参与计算
        # persist_start_date 为持久化截断下限，防止水位返回早期日期时持久化超出5年范围
        start_date = str(ctx.get("start_date", ""))
        persist_start_date = str(ctx.get("persist_start_date", ""))
        # 取水位日期与持久化下限的较晚者作为实际截断日期
        if persist_start_date and start_date:
            actual_cutoff = max(start_date, persist_start_date)
        elif persist_start_date:
            actual_cutoff = persist_start_date
        else:
            actual_cutoff = start_date
        cutoff_date = _parse_cutoff(actual_cutoff)

        # 向量化过滤：截断日期
        if cutoff_date is not None:
            td_series = pd.to_datetime(df["trade_date"])
            mask = td_series.dt.date >= cutoff_date
            df_filtered = df.loc[mask]
            logger.info(
                "[factor.compute] %s cutoff=%s total=%d filtered=%d td_type=%s td_sample=%s",
                symbol, cutoff_date, len(df), len(df_filtered),
                type(df["trade_date"].iloc[0]).__name__ if len(df) > 0 else "empty",
                df["trade_date"].iloc[0] if len(df) > 0 else "N/A",
            )
        else:
            df_filtered = df

        if df_filtered.empty:
            return StageResult.ok(data={"symbol": symbol, "persisted": 0})

        # 向量化构建窄表行
        trade_dates = pd.to_datetime(df_filtered["trade_date"]).dt.date.values
        rows = self._build_rows_vectorized(symbol, trade_dates, df_filtered[factor_cols])

        if not rows:
            return StageResult.ok(data={"symbol": symbol, "persisted": 0})

        count = await FacFactorValue.bulk_create_or_update(
            rows,  # type: ignore[arg-type]
            on_conflict=["symbol", "trade_date", "factor_id", "pool_id"],
            update_fields=["factor_value"],
            batch_size=_BATCH_SIZE,
        )

        # 设置 persisted_count 和 max_trade_date，供水位 Aspect 后切更新水位
        ctx.set("persisted_count", count)
        if count > 0:
            max_td = trade_dates.max()
            if max_td is not None:
                ctx.set("max_trade_date", max_td)

        logger.info(
            "[factor.compute] %s upserted=%d rows_built=%d factors=%d cutoff=%s",
            symbol, count, len(rows), len(factor_cols), actual_cutoff,
        )
        return StageResult.ok(data={"symbol": symbol, "persisted": count})

    @staticmethod
    def _build_rows_vectorized(
        symbol: str,
        trade_dates: np.ndarray,
        factor_df: pd.DataFrame,
    ) -> list[FacFactorValue]:
        """向量化构建 FacFactorValue 行列表，避免逐行 Python 循环。"""
        rows: list[FacFactorValue] = []
        n_dates = len(trade_dates)
        n_factors = len(factor_df.columns)
        factor_ids = factor_df.columns.tolist()
        values = factor_df.values  # shape: (n_dates, n_factors)

        for i in range(n_dates):
            td = trade_dates[i]
            if td is None:
                continue
            for j in range(n_factors):
                val = values[i, j]
                if np.isnan(val):
                    continue
                rows.append(FacFactorValue(
                    symbol=symbol,
                    trade_date=td,
                    factor_id=factor_ids[j],
                    pool_id="all",
                    factor_value=float(val),
                ))
        return rows
