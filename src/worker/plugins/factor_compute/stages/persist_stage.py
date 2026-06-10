"""持久化阶段 — 将因子值写入 fac_factor_value 表。

策略：
  - 根据 start_date 只持久化增量部分数据（预热期和更早数据仅参与计算不持久化）
  - 窄表格式：每行一个因子值
  - pool_id 默认 "all"
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from framework.commons.logger import get_logger
from framework.pipeline import PipelineContext, Stage, StageResult
from xqtrader.domain.factor.models.factor_value import FacFactorValue

logger = get_logger("factor.persist")


def _normalize_trade_date(value: Any) -> date | None:
    """将各种格式的交易日期转换为 date 对象。"""
    # pd.Timestamp 是 datetime 的子类，datetime 是 date 的子类
    # 必须先检查 Timestamp/datetime，再检查 date
    if hasattr(value, "date") and callable(value.date):
        return value.date()  # type: ignore[no-any-return]
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                if fmt == "%Y-%m-%d":
                    return date.fromisoformat(value)
                return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
            except (ValueError, IndexError):
                continue
    return None


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
        start_date = str(ctx.get("start_date", ""))
        cutoff_date = _parse_cutoff(start_date)

        # 转换为窄表
        long_df = df.melt(
            id_vars=["trade_date"],
            value_vars=factor_cols,
            var_name="factor_id",
            value_name="factor_value",
        )
        long_df = long_df.dropna(subset=["factor_value"])

        rows: list[FacFactorValue] = []
        for record in long_df.itertuples(index=False):
            trade_date = _normalize_trade_date(record.trade_date)
            if trade_date is None:
                continue
            # 只持久化 start_date 之后的数据
            if cutoff_date and trade_date < cutoff_date:
                continue
            rows.append(FacFactorValue(
                symbol=symbol,
                trade_date=trade_date,
                factor_id=record.factor_id,
                pool_id="all",
                factor_value=float(record.factor_value),  # type: ignore[arg-type]
            ))

        if not rows:
            return StageResult.ok(data={"symbol": symbol, "persisted": 0})

        count = await FacFactorValue.bulk_create_or_update(
            rows,  # type: ignore[arg-type]
            on_conflict=["symbol", "trade_date", "factor_id", "pool_id"],
            update_fields=["factor_value"],
            batch_size=500,
        )

        logger.info("[persist] %s upserted=%d factors=%d cutoff=%s", symbol, count, len(factor_cols), start_date)
        return StageResult.ok(data={"symbol": symbol, "persisted": count})
