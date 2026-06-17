"""加权评分组合策略"""

from __future__ import annotations

from typing import Any

from ..base import RuleResult
from .base import CombinationStrategy


class WeightedScoreCombination(CombinationStrategy):
    """加权评分组合 — score = Σ(w_i × score_i) / Σ(w_i)"""

    method = "weighted_score"

    def combine(
        self,
        rule_results: list[RuleResult],
        weights: dict[str, float] | None = None,
        params: dict[str, Any] | None = None,
    ) -> RuleResult:
        weights = weights or {}
        params = params or {}
        threshold = params.get("threshold", 0.5)

        if not rule_results:
            return RuleResult(rule_id="combined_weighted_score", passed=False)

        total_weight = 0.0
        weighted_score = 0.0
        weighted_conf = 0.0

        for r in rule_results:
            w = weights.get(r.rule_id, 1.0 / len(rule_results))
            weighted_score += w * r.score
            weighted_conf += w * r.confidence
            total_weight += w

        score = weighted_score / total_weight if total_weight > 0 else 0.0
        confidence = weighted_conf / total_weight if total_weight > 0 else 0.0
        passed = score >= threshold

        # 方向：加权投票
        direction = self._weighted_direction(rule_results, weights)

        return RuleResult(
            rule_id="combined_weighted_score",
            passed=passed,
            score=score,
            direction=direction,
            confidence=confidence,
            detail={"method": "weighted_score", "threshold": threshold, "weights": weights},
        )

    @staticmethod
    def _weighted_direction(
        results: list[RuleResult],
        weights: dict[str, float],
    ) -> str:
        long_w = sum(weights.get(r.rule_id, 0) for r in results if r.direction == "long")
        short_w = sum(weights.get(r.rule_id, 0) for r in results if r.direction == "short")
        if long_w > short_w and long_w > 0:
            return "long"
        if short_w > long_w and short_w > 0:
            return "short"
        return "neutral"
