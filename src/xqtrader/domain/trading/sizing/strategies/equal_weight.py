"""等权仓位策略 — 每个标的分配相同权重。"""

from __future__ import annotations

from typing import Any

from ...signals.fusion import FusionResult
from ..base import PortfolioState, PositionSizingStrategy, SizingContext, SizingResult


class EqualWeightStrategy(PositionSizingStrategy):
    """等权策略 — w_i = 1/N。"""

    strategy_name = "equal_weight"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
        }

    async def prepare(self, context: SizingContext) -> None:
        """无需预加载数据。"""

    def compute_weights(
        self,
        signals: dict[str, FusionResult],
        portfolio: PortfolioState,
        market_data: dict[str, Any] | None = None,
    ) -> dict[str, SizingResult]:
        n = len(signals)
        if n == 0:
            return {}
        weight = 1.0 / n
        return {
            symbol: SizingResult(
                symbol=symbol,
                target_weight=weight,
                sizing_strategy=self.strategy_name,
                raw_score=weight,
            )
            for symbol in signals
        }
