"""AND / OR 逻辑组合策略"""

from __future__ import annotations

from typing import Any

from ..base import RuleResult
from .base import CombinationStrategy


class AndCombination(CombinationStrategy):
    """AND 组合 — 全部通过才通过，score=min，confidence=min"""

    method = "and"

    def combine(
        self,
        rule_results: list[RuleResult],
        weights: dict[str, float] | None = None,
        params: dict[str, Any] | None = None,
    ) -> RuleResult:
        if not rule_results:
            return RuleResult(rule_id="combined_and", passed=False)

        passed = all(r.passed for r in rule_results)
        score = min(r.score for r in rule_results) if rule_results else 0.0
        confidence = min(r.confidence for r in rule_results) if rule_results else 0.0

        # 方向：全部一致取之，否则 neutral
        directions = {r.direction for r in rule_results if r.direction != "neutral"}
        direction = directions.pop() if len(directions) == 1 else "neutral"

        return RuleResult(
            rule_id="combined_and",
            passed=passed,
            score=score,
            direction=direction,
            confidence=confidence,
            detail={"method": "and", "sub_results": [r.rule_id for r in rule_results]},
        )


class OrCombination(CombinationStrategy):
    """OR 组合 — 任一通过即通过，score=max，confidence=max"""

    method = "or"

    def combine(
        self,
        rule_results: list[RuleResult],
        weights: dict[str, float] | None = None,
        params: dict[str, Any] | None = None,
    ) -> RuleResult:
        if not rule_results:
            return RuleResult(rule_id="combined_or", passed=False)

        passed = any(r.passed for r in rule_results)
        score = max(r.score for r in rule_results) if rule_results else 0.0
        confidence = max(r.confidence for r in rule_results) if rule_results else 0.0

        # 方向：取置信度最高的
        best = max(rule_results, key=lambda r: r.confidence)
        direction = best.direction

        return RuleResult(
            rule_id="combined_or",
            passed=passed,
            score=score,
            direction=direction,
            confidence=confidence,
            detail={"method": "or", "sub_results": [r.rule_id for r in rule_results]},
        )
