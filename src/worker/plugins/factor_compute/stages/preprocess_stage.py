"""预处理阶段 — 透传因子值。

逐标的因子计算管线中不做截面预处理（MAD去极值/Z-score/行业中性化）。
原因：MAD是截面操作，需同日全市场标的数据才有意义；单标的时序上的"极值"往往是有效信号。
截面预处理在评估/合成时的 CrossSectionReader 中完成。
"""

from __future__ import annotations

from typing import Any

from framework.commons.logger import get_logger
from framework.pipeline import PipelineContext, Stage, StageResult

logger = get_logger("factor.preprocess")


class FactorPreprocessStage(Stage):
    """预处理阶段 — 透传因子值，截面预处理留给 CrossSectionReader。"""

    @property
    def name(self) -> str:
        return "factor_preprocess"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        symbol: str = item

        if ctx.get("skip_persist"):
            return StageResult.ok(data={"symbol": symbol, "processed": 0})

        df: Any | None = ctx.get("factor_df")
        if df is None or df.empty:
            return StageResult.ok(data={"symbol": symbol, "processed": 0})

        factor_cols = [c for c in df.columns if c not in ("symbol", "trade_date")]
        logger.info(
            "[preprocess] %s passed-through %d factors (cross-section prep deferred to CrossSectionReader)",
            symbol, len(factor_cols),
        )
        return StageResult.ok(data={"symbol": symbol, "processed": len(factor_cols)})
