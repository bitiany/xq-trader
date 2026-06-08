"""因子持久化阶段 — 将单只股票多日因子值批量写入 fac_factor_value。

从 PipelineContext 读取 factor_df（DataFrame，含多日多因子），
展开为窄表行，批量 upsert。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from framework.commons.logger import get_logger
from framework.pipeline import PipelineContext, Stage, StageResult
from xqtrader.domain.factor.exceptions import FactorPersistError
from xqtrader.domain.factor.models.factor_value import FacFactorValue

logger = get_logger(__name__)


class FactorPersistStage(Stage):
    """因子持久化阶段 — 将单只股票的批量因子值写入 fac_factor_value。

    写入模式：bulk_create_or_update（upsert），冲突键为 (symbol, trade_date, factor_id, pool_id)。
    """

    @property
    def name(self) -> str:
        return "factor_persist"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        stock_code: str = item

        factor_df: pd.DataFrame | None = ctx.get("factor_df")
        if factor_df is None or factor_df.empty:
            return StageResult.ok(data={"stock_code": stock_code, "persisted": 0})

        try:
            instances = self._build_instances(stock_code, factor_df)
            if not instances:
                return StageResult.ok(data={"stock_code": stock_code, "persisted": 0})

            count = await FacFactorValue.bulk_create_or_update(
                instances,  # type: ignore[arg-type]
                on_conflict=["symbol", "trade_date", "factor_id", "pool_id"],
                update_fields=["factor_value"],
                batch_size=500,
            )

            logger.debug("因子持久化完成: %s rows=%d", stock_code, count)
            return StageResult.ok(data={"stock_code": stock_code, "persisted": count})

        except FactorPersistError as e:
            logger.error("因子持久化失败: %s error=%s", stock_code, e)
            return StageResult.fail(f"因子持久化失败 {stock_code}: {e}")

    @staticmethod
    def _build_instances(stock_code: str, factor_df: pd.DataFrame) -> list[FacFactorValue]:
        """将宽表 DataFrame 展开为 FacFactorValue 实例列表（向量化melt）。"""
        factor_cols = [c for c in factor_df.columns if c != "trade_date"]
        if not factor_cols:
            return []

        # 确保 trade_date 为 date 类型（merge_asof 可能将其转为 datetime64）
        if pd.api.types.is_datetime64_any_dtype(factor_df["trade_date"]):
            factor_df = factor_df.copy()
            factor_df["trade_date"] = factor_df["trade_date"].dt.date

        # 仅保留数值类型列（排除非因子列如 symbol/ann_date/end_date 等）
        numeric_cols = [c for c in factor_cols if pd.api.types.is_numeric_dtype(factor_df[c])]
        non_numeric_cols = [c for c in factor_cols if c not in numeric_cols]
        if non_numeric_cols:
            logger.warning("因子持久化跳过非数值列: stock=%s cols=%s", stock_code, non_numeric_cols)
        if not numeric_cols:
            return []

        # melt 宽表 → 长表
        melted = factor_df.melt(
            id_vars=["trade_date"],
            value_vars=numeric_cols,
            var_name="factor_id",
            value_name="factor_value",
        )

        # 过滤无效值
        valid = melted.dropna(subset=["factor_value"])
        valid = valid[np.isfinite(valid["factor_value"])]

        instances: list[FacFactorValue] = []
        for row in valid.itertuples(index=False):
            instances.append(FacFactorValue(
                symbol=stock_code,
                trade_date=row.trade_date,
                factor_id=row.factor_id,
                pool_id="all",
                factor_value=float(row.factor_value),
            ))
        return instances
