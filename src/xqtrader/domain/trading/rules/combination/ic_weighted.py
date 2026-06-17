"""IC 加权组合策略"""

from __future__ import annotations

from typing import Any

from ..base import RuleResult
from .base import CombinationStrategy


class ICWeightedCombination(CombinationStrategy):
    """IC 加权组合 — score = Σ(ICIR_i × zscore_i) / Σ|ICIR_i|

    仅适用于截面选股，权重来自因子历史 ICIR。
    """

    method = "ic_weighted"

    def combine(
        self,
        rule_results: list[RuleResult],
        weights: dict[str, float] | None = None,
        params: dict[str, Any] | None = None,
    ) -> RuleResult:
        weights = weights or {}
        params = params or {}
        threshold = params.get("threshold", 0.0)

        if not rule_results:
            return RuleResult(rule_id="combined_ic_weighted", passed=False)

        # weights 即 ICIR 值
        total_abs_icir = sum(abs(weights.get(r.rule_id, 0.0)) for r in rule_results)

        if total_abs_icir == 0:
            # 无 ICIR 数据时退化为等权
            weights = {r.rule_id: 1.0 / len(rule_results) for r in rule_results}
            total_abs_icir = 1.0

        weighted_score = 0.0
        for r in rule_results:
            icir = weights.get(r.rule_id, 0.0)
            weighted_score += icir * r.score

        score = weighted_score / total_abs_icir if total_abs_icir > 0 else 0.0
        passed = score >= threshold
        confidence = abs(score)

        direction = "long" if score > 0 else ("short" if score < 0 else "neutral")

        return RuleResult(
            rule_id="combined_ic_weighted",
            passed=passed,
            score=score,
            direction=direction,
            confidence=confidence,
            detail={"method": "ic_weighted", "threshold": threshold, "icir_weights": weights},
        )
