"""信号强度加权仓位策略 — 按融合得分分配权重。"""

from __future__ import annotations

from typing import Any

from ...signals.fusion import FusionResult
from ..base import PortfolioState, PositionSizingStrategy, SizingContext, SizingResult


class SignalWeightStrategy(PositionSizingStrategy):
    """信号强度加权 — w_i = score_i / Σ(score_j)。"""

    strategy_name = "signal_weight"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "min_weight": {
                    "type": "number",
                    "default": 0.0,
                    "description": "最小权重下限",
                },
            },
        }

    async def prepare(self, context: SizingContext) -> None:
        """无需预加载数据。"""

    def compute_weights(
        self,
        signals: dict[str, FusionResult],
        portfolio: PortfolioState,
        market_data: dict[str, Any] | None = None,
    ) -> dict[str, SizingResult]:
        if not signals:
            return {}

        total_score = sum(max(s.fused_score, 0.0) for s in signals.values())
        if total_score <= 0:
            # 全部得分非正时退化为等权
            weight = 1.0 / len(signals)
            return {
                symbol: SizingResult(
                    symbol=symbol,
                    target_weight=weight,
                    sizing_strategy=self.strategy_name,
                    raw_score=0.0,
                )
                for symbol in signals
            }

        return {
            symbol: SizingResult(
                symbol=symbol,
                target_weight=max(signal.fused_score, 0.0) / total_score,
                sizing_strategy=self.strategy_name,
                raw_score=signal.fused_score,
            )
            for symbol, signal in signals.items()
        }
