"""组合约束层 — 对仓位策略输出施加组合级约束。

约束类型:
  1. 单标的最大权重: cap each position to max_single_position
  2. 行业集中度: cap each industry's total weight to max_industry_concentration
  3. 总权重上限: cap total weight to max_total_weight (留现金比例)
  4. 归一化: 约束后重新归一化权重
"""

from __future__ import annotations

from typing import Any

from framework.commons.logger import get_logger

from .base import PortfolioState, SizingResult

logger = get_logger(__name__)


class PortfolioConstraints:
    """组合约束层 — 对仓位策略输出施加组合级约束。"""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self.max_single_position: float = float(config.get("max_single_position", 0.20))
        self.max_industry_concentration: float = float(
            config.get("max_industry_concentration", 0.30)
        )
        self.max_total_weight: float = float(config.get("max_total_weight", 1.0))
        self._industry_map: dict[str, str] = {}

    def set_industry_map(self, industry_map: dict[str, str]) -> None:
        """设置标的→行业映射。"""
        self._industry_map = dict(industry_map)

    def apply(
        self,
        results: dict[str, SizingResult],
        portfolio: PortfolioState,
    ) -> dict[str, SizingResult]:
        """依序施加约束：单标的上限 → 行业集中度 → 总权重 → 归一化。"""
        if not results:
            return results

        results = self._apply_single_position_cap(results)
        results = self._apply_industry_concentration(results)
        results = self._apply_total_weight_cap(results)
        results = self._renormalize(results)
        return results

    def _apply_single_position_cap(
        self, results: dict[str, SizingResult],
    ) -> dict[str, SizingResult]:
        """单标的权重上限。"""
        for symbol, result in results.items():
            if result.target_weight > self.max_single_position:
                logger.debug(
                    f"单标的权重约束: {symbol} {result.target_weight:.4f} → {self.max_single_position:.4f}"
                )
                result.target_weight = self.max_single_position
        return results

    def _apply_industry_concentration(
        self, results: dict[str, SizingResult],
    ) -> dict[str, SizingResult]:
        """行业集中度约束 — 超额行业按比例缩减。"""
        if not self._industry_map:
            return results

        industry_weights: dict[str, float] = {}
        industry_symbols: dict[str, list[str]] = {}
        for symbol, result in results.items():
            industry = self._industry_map.get(symbol, "unknown")
            industry_weights[industry] = industry_weights.get(industry, 0.0) + result.target_weight
            industry_symbols.setdefault(industry, []).append(symbol)

        for industry, total_w in industry_weights.items():
            if total_w > self.max_industry_concentration:
                scale = self.max_industry_concentration / total_w
                for symbol in industry_symbols[industry]:
                    results[symbol].target_weight *= scale
                logger.debug(
                    f"行业集中度约束: {industry} {total_w:.4f} → {self.max_industry_concentration:.4f}"
                )
        return results

    def _apply_total_weight_cap(
        self, results: dict[str, SizingResult],
    ) -> dict[str, SizingResult]:
        """总权重上限约束。"""
        total = sum(r.target_weight for r in results.values())
        if total > self.max_total_weight:
            scale = self.max_total_weight / total
            for result in results.values():
                result.target_weight *= scale
            logger.debug(
                f"总权重约束: {total:.4f} → {self.max_total_weight:.4f}"
            )
        return results

    @staticmethod
    def _renormalize(results: dict[str, SizingResult]) -> dict[str, SizingResult]:
        """归一化 — 确保权重非负且总和 ≤ 1.0。"""
        for result in results.values():
            if result.target_weight < 0:
                result.target_weight = 0.0
        return results
