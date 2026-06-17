"""组合策略单元测试"""

import pytest

from xqtrader.domain.trading.rules.base import RuleResult
from xqtrader.domain.trading.rules.combination.and_or import AndCombination, OrCombination
from xqtrader.domain.trading.rules.combination.weighted_score import WeightedScoreCombination
from xqtrader.domain.trading.rules.combination.weighted_vote import WeightedVoteCombination
from xqtrader.domain.trading.rules.combination.ic_weighted import ICWeightedCombination


def _make_result(rule_id: str, passed: bool, score: float = 0.0,
                 direction: str = "neutral", confidence: float = 0.0) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        passed=passed,
        score=score,
        direction=direction,
        confidence=confidence,
    )


class TestAndCombination:

    def test_all_passed(self):
        combo = AndCombination()
        results = [
            _make_result("r1", True, 0.8, "long", 0.8),
            _make_result("r2", True, 0.6, "long", 0.6),
        ]
        combined = combo.combine(results)
        assert combined.passed is True
        assert combined.score == 0.6  # min
        assert combined.confidence == 0.6  # min

    def test_one_failed(self):
        combo = AndCombination()
        results = [
            _make_result("r1", True, 0.8, "long", 0.8),
            _make_result("r2", False, 0.0, "neutral", 0.0),
        ]
        combined = combo.combine(results)
        assert combined.passed is False

    def test_empty_results(self):
        combo = AndCombination()
        combined = combo.combine([])
        assert combined.passed is False


class TestOrCombination:

    def test_one_passed(self):
        combo = OrCombination()
        results = [
            _make_result("r1", False, 0.0, "neutral", 0.0),
            _make_result("r2", True, 0.6, "long", 0.6),
        ]
        combined = combo.combine(results)
        assert combined.passed is True
        assert combined.score == 0.6  # max

    def test_all_failed(self):
        combo = OrCombination()
        results = [
            _make_result("r1", False, 0.0, "neutral", 0.0),
            _make_result("r2", False, 0.0, "neutral", 0.0),
        ]
        combined = combo.combine(results)
        assert combined.passed is False


class TestWeightedScoreCombination:

    def test_weighted_score(self):
        combo = WeightedScoreCombination()
        results = [
            _make_result("r1", True, 0.8, "long", 0.8),
            _make_result("r2", True, 0.6, "long", 0.6),
        ]
        weights = {"r1": 0.6, "r2": 0.4}
        combined = combo.combine(results, weights, {"threshold": 0.5})
        expected_score = (0.6 * 0.8 + 0.4 * 0.6) / 1.0
        assert abs(combined.score - expected_score) < 0.01
        assert combined.passed is True

    def test_below_threshold(self):
        combo = WeightedScoreCombination()
        results = [
            _make_result("r1", True, 0.3, "long", 0.3),
            _make_result("r2", True, 0.2, "long", 0.2),
        ]
        combined = combo.combine(results, params={"threshold": 0.5})
        assert combined.passed is False

    def test_equal_weights(self):
        combo = WeightedScoreCombination()
        results = [
            _make_result("r1", True, 0.6, "long", 0.6),
            _make_result("r2", True, 0.4, "long", 0.4),
        ]
        combined = combo.combine(results, params={"threshold": 0.0})
        assert abs(combined.score - 0.5) < 0.01


class TestWeightedVoteCombination:

    def test_long_consensus(self):
        combo = WeightedVoteCombination()
        results = [
            _make_result("r1", True, 0.8, "long", 0.8),
            _make_result("r2", True, 0.6, "long", 0.6),
        ]
        weights = {"r1": 0.5, "r2": 0.5}
        combined = combo.combine(results, weights, {"threshold": 0.3})
        assert combined.direction == "long"
        assert combined.passed is True

    def test_mixed_directions(self):
        combo = WeightedVoteCombination()
        results = [
            _make_result("r1", True, 0.8, "long", 0.8),
            _make_result("r2", True, 0.6, "short", 0.6),
        ]
        weights = {"r1": 0.7, "r2": 0.3}
        combined = combo.combine(results, weights, {"threshold": 0.1})
        assert combined.direction == "long"  # long 权重更大


class TestICWeightedCombination:

    def test_ic_weighted(self):
        combo = ICWeightedCombination()
        results = [
            _make_result("r1", True, 0.5, "long", 0.5),
            _make_result("r2", True, 0.3, "long", 0.3),
        ]
        icir_weights = {"r1": 2.0, "r2": 1.0}
        combined = combo.combine(results, icir_weights, {"threshold": 0.0})
        # score = (2.0*0.5 + 1.0*0.3) / (|2.0|+|1.0|) = 1.3/3.0 ≈ 0.433
        assert abs(combined.score - 0.433) < 0.01
        assert combined.direction == "long"

    def test_no_icir_fallback_equal_weight(self):
        combo = ICWeightedCombination()
        results = [
            _make_result("r1", True, 0.6, "long", 0.6),
            _make_result("r2", True, 0.4, "long", 0.4),
        ]
        combined = combo.combine(results, params={"threshold": 0.0})
        # ICIR 全 0 时退化为等权
        assert abs(combined.score - 0.5) < 0.01
