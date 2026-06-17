"""加权投票组合策略"""

from __future__ import annotations

from typing import Any

from ..base import RuleResult
from .base import CombinationStrategy


class WeightedVoteCombination(CombinationStrategy):
    """加权投票组合 — |Σ(w_i × direction_i × conf_i)| / Σ(w_i)"""

    method = "weighted_vote"

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
            return RuleResult(rule_id="combined_weighted_vote", passed=False)

        direction_map = {"long": 1, "short": -1, "neutral": 0}

        total_weight = 0.0
        weighted_vote = 0.0

        for r in rule_results:
            w = weights.get(r.rule_id, 1.0 / len(rule_results))
            d = direction_map.get(r.direction, 0)
            weighted_vote += w * d * r.confidence
            total_weight += w

        confidence = abs(weighted_vote) / total_weight if total_weight > 0 else 0.0
        passed = confidence >= threshold

        direction = "neutral"
        if weighted_vote > 0:
            direction = "long"
        elif weighted_vote < 0:
            direction = "short"

        score = confidence

        return RuleResult(
            rule_id="combined_weighted_vote",
            passed=passed,
            score=score,
            direction=direction,
            confidence=confidence,
            detail={"method": "weighted_vote", "threshold": threshold, "weights": weights},
        )
