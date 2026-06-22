"""固定比例仓位策略 — 每个标的分配固定权重。"""

from __future__ import annotations

from typing import Any

from ...signals.fusion import FusionResult
from ..base import PortfolioState, PositionSizingStrategy, SizingContext, SizingResult


class FixedFractionStrategy(PositionSizingStrategy):
    """固定比例策略 — w_i = fixed_pct。

    适用于标的数量固定的场景，每个标的分配相同固定比例。
    """

    strategy_name = "fixed_fraction"

    def __init__(self) -> None:
        self._fixed_pct: float = 0.10

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "fixed_pct": {
                    "type": "number",
                    "default": 0.10,
                    "description": "每个标的固定权重比例",
                },
            },
        }

    async def prepare(self, context: SizingContext) -> None:
        self._fixed_pct = float(context.params.get("fixed_pct", 0.10))

    def compute_weights(
        self,
        signals: dict[str, FusionResult],
        portfolio: PortfolioState,
        market_data: dict[str, Any] | None = None,
    ) -> dict[str, SizingResult]:
        return {
            symbol: SizingResult(
                symbol=symbol,
                target_weight=self._fixed_pct,
                sizing_strategy=self.strategy_name,
                raw_score=self._fixed_pct,
            )
            for symbol in signals
        }
