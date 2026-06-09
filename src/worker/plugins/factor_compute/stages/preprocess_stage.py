"""预处理阶段 — 去极值（MAD）。

截面标准化（Z-score/行业中性化）在评估/合成时的 CrossSectionReader 中完成，
不在因子计算任务中处理。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from framework.commons.logger import get_logger
from framework.pipeline import PipelineContext, Stage, StageResult

logger = get_logger("factor.preprocess")

_MAD_SCALE = 1.4826  # MAD → 标准差的换算系数
_MAD_THRESHOLD = 3.0  # 3倍标准差外为极端值


def _mad_winsorize(series: pd.Series, threshold: float = _MAD_THRESHOLD) -> pd.Series:
    """MAD 去极值 — 将超出 threshold 倍 MAD 的值截断到边界。"""
    median = series.median()
    mad = (series - median).abs().median() * _MAD_SCALE
    if mad == 0 or np.isnan(mad):
        return series
    lower = median - threshold * mad
    upper = median + threshold * mad
    return series.clip(lower=lower, upper=upper)


class FactorPreprocessStage(Stage):
    """预处理阶段 — 逐标的 MAD 去极值。"""

    @property
    def name(self) -> str:
        return "factor_preprocess"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        symbol: str = item

        if ctx.get("skip_persist"):
            return StageResult.ok(data={"symbol": symbol, "processed": 0})

        df: pd.DataFrame | None = ctx.get("factor_df")
        if df is None or df.empty:
            return StageResult.ok(data={"symbol": symbol, "processed": 0})

        factor_cols = [c for c in df.columns if c not in ("symbol", "trade_date")]
        if not factor_cols:
            return StageResult.ok(data={"symbol": symbol, "processed": 0})

        # 跳过标记为 skip_preprocess 的因子列（如前向收益率）
        skip_cols: set[str] = ctx.get("skip_preprocess_cols") or set()
        process_cols = [c for c in factor_cols if c not in skip_cols]

        # 逐列去极值
        for col in process_cols:
            df[col] = _mad_winsorize(df[col])

        ctx.set("factor_df", df)

        logger.info(
            "[preprocess] %s processed=%d factors",
            symbol, len(factor_cols),
        )
        return StageResult.ok(data={"symbol": symbol, "processed": len(factor_cols)})
