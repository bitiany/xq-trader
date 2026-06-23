"""AND / OR 逻辑融合策略"""

from ..core import FusionConfig, RuleResult
from .base import FusionStrategy


class AndFusion(FusionStrategy):
    """AND 融合 — 所有规则通过且方向一致才产生信号

    逻辑:
      - 所有规则的 passed=True 且方向一致（全 buy 或全 sell）才产生信号
      - 方向冲突或部分未通过则返回 neutral
      - 融合 score 取最小值（保守），confidence 取最小值
    """

    def fuse(self, results: list[RuleResult], config: FusionConfig) -> RuleResult:
        if not results:
            return RuleResult(rule_id="fusion", direction="neutral", reason="AND: 无规则结果")

        all_passed = all(r.passed for r in results)
        if not all_passed:
            failed = [r.rule_id for r in results if not r.passed]
            return RuleResult(
                rule_id="fusion", direction="neutral",
                reason=f"AND: 部分规则未通过 {failed}",
            )

        positive_results = [r for r in results if r.direction in {"buy", "bullish"}]
        negative_results = [r for r in results if r.direction in {"sell", "bearish"}]

        if positive_results and not negative_results:
            return RuleResult(
                rule_id="fusion", passed=True,
                score=min(r.score for r in positive_results),
                direction=positive_results[0].direction,
                confidence=min(r.confidence for r in positive_results),
                reason="AND买入: " + " & ".join(r.reason for r in positive_results),
            )

        if negative_results and not positive_results:
            return RuleResult(
                rule_id="fusion", passed=True,
                score=min(r.score for r in negative_results),
                direction=negative_results[0].direction,
                confidence=min(r.confidence for r in negative_results),
                reason="AND卖出: " + " & ".join(r.reason for r in negative_results),
            )

        return RuleResult(
            rule_id="fusion", direction="neutral",
            reason="AND: 方向冲突，未产生一致信号",
        )


class OrFusion(FusionStrategy):
    """OR 融合 — 任一规则触发即产生信号（buy 优先）

    逻辑:
      - 任一规则 direction=buy 则产生 buy 信号（取第一个触发的）
      - 任一规则 direction=sell 则产生 sell 信号（取第一个触发的）
      - 同时触发时 buy 优先
      - 融合 score/confidence 取触发规则的值
    """

    def fuse(self, results: list[RuleResult], config: FusionConfig) -> RuleResult:
        if not results:
            return RuleResult(rule_id="fusion", direction="neutral", reason="OR: 无规则结果")

        positive_result = next((r for r in results if r.direction in {"buy", "bullish"}), None)
        negative_result = next((r for r in results if r.direction in {"sell", "bearish"}), None)

        if positive_result:
            return RuleResult(
                rule_id="fusion", passed=True,
                score=positive_result.score,
                direction=positive_result.direction,
                confidence=positive_result.confidence,
                reason=positive_result.reason,
            )

        if negative_result:
            return RuleResult(
                rule_id="fusion", passed=True,
                score=negative_result.score,
                direction=negative_result.direction,
                confidence=negative_result.confidence,
                reason=negative_result.reason,
            )

        return RuleResult(rule_id="fusion", direction="neutral", reason="OR: 无信号")
