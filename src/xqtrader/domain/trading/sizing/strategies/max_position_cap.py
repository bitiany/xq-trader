"""最大持仓上限策略 — 等权分配但单标的不超过上限。"""

from __future__ import annotations

from typing import Any

from ...signals.fusion import FusionResult
from ..base import PortfolioState, PositionSizingStrategy, SizingContext, SizingResult


class MaxPositionCapStrategy(PositionSizingStrategy):
    """最大持仓上限 — w_i = min(1/N, cap)。

    等权分配，但单标的权重不超过 cap。超出部分按比例分配给其他标的。
    """

    strategy_name = "max_position_cap"

    def __init__(self) -> None:
        self._cap: float = 0.20

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "cap": {
                    "type": "number",
                    "default": 0.20,
                    "description": "单标的最大权重上限",
                },
            },
        }

    async def prepare(self, context: SizingContext) -> None:
        self._cap = float(context.params.get("cap", 0.20))

    def compute_weights(
        self,
        signals: dict[str, FusionResult],
        portfolio: PortfolioState,
        market_data: dict[str, Any] | None = None,
    ) -> dict[str, SizingResult]:
        n = len(signals)
        if n == 0:
            return {}

        equal_weight = 1.0 / n
        if equal_weight <= self._cap:
            # 等权未超上限，直接等权
            return {
                symbol: SizingResult(
                    symbol=symbol,
                    target_weight=equal_weight,
                    sizing_strategy=self.strategy_name,
                    raw_score=equal_weight,
                )
                for symbol in signals
            }

        # 等权超上限：每个标的分配 cap，剩余按比例分配给未达上限的标的
        return self._distribute_with_cap(list(signals.keys()))

    def _distribute_with_cap(self, symbols: list[str]) -> dict[str, SizingResult]:
        """迭代分配：每标的最多 cap，剩余按比例分配。"""
        weights = {s: min(1.0 / len(symbols), self._cap) for s in symbols}
        remaining = 1.0 - sum(weights.values())

        while remaining > 1e-6:
            uncapped = [s for s in symbols if weights[s] < self._cap]
            if not uncapped:
                break
            share = remaining / len(uncapped)
            for s in uncapped:
                addition = min(share, self._cap - weights[s])
                weights[s] += addition
            remaining = 1.0 - sum(weights.values())

        return {
            s: SizingResult(
                symbol=s,
                target_weight=weights[s],
                sizing_strategy=self.strategy_name,
                raw_score=weights[s],
            )
            for s in symbols
        }
