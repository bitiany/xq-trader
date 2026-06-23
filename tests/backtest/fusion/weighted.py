"""加权评分 / 加权投票融合策略"""

from ..core import FusionConfig, RuleResult
from .base import FusionStrategy


def _direction_signal(direction: str) -> float:
    """将方向转换为数值信号: buy→+1, sell→-1, neutral→0"""
    if direction == "buy":
        return 1.0
    if direction == "sell":
        return -1.0
    return 0.0


class WeightedScoreFusion(FusionStrategy):
    """加权评分融合 — score × direction 加权求和后与阈值比较

    公式:
      weighted_score = Σ(w_i × score_i × signal_i) / Σ(w_i)
      signal_i = +1 (buy) / -1 (sell) / 0 (neutral)

      若 weighted_score >= buy_threshold → buy
      若 weighted_score <= -sell_threshold → sell
      否则 neutral
    """

    def fuse(self, results: list[RuleResult], config: FusionConfig) -> RuleResult:
        if not results:
            return RuleResult(rule_id="fusion", direction="neutral", reason="加权评分: 无规则结果")

        weights = config.weights
        total_weight = sum(weights.get(r.rule_id, 1.0) for r in results)
        if total_weight == 0:
            return RuleResult(rule_id="fusion", direction="neutral", reason="加权评分: 权重全为0")

        weighted_score = 0.0
        for r in results:
            w = weights.get(r.rule_id, 1.0)
            signal = _direction_signal(r.direction)
            weighted_score += w * r.score * signal

        normalized = weighted_score / total_weight

        if normalized >= config.buy_threshold:
            return RuleResult(
                rule_id="fusion", passed=True,
                score=abs(normalized),
                direction="buy",
                confidence=abs(normalized),
                reason=f"加权评分买入: score={normalized:.4f} >= {config.buy_threshold}",
            )

        if normalized <= -config.sell_threshold:
            return RuleResult(
                rule_id="fusion", passed=True,
                score=abs(normalized),
                direction="sell",
                confidence=abs(normalized),
                reason=f"加权评分卖出: score={normalized:.4f} <= -{config.sell_threshold}",
            )

        return RuleResult(
            rule_id="fusion", direction="neutral",
            reason=f"加权评分: score={normalized:.4f} 未达阈值(±{config.buy_threshold})",
        )


class WeightedVoteFusion(FusionStrategy):
    """加权投票融合 — 方向投票加权求和后与阈值比较

    公式:
      vote = Σ(w_i × signal_i) / Σ(w_i)
      signal_i = +1 (buy) / -1 (sell) / 0 (neutral)

      若 vote >= buy_threshold → buy
      若 vote <= -sell_threshold → sell
      否则 neutral

    与加权评分的区别: 投票只看方向不看 score 强度，每票等权。
    """

    def fuse(self, results: list[RuleResult], config: FusionConfig) -> RuleResult:
        if not results:
            return RuleResult(rule_id="fusion", direction="neutral", reason="加权投票: 无规则结果")

        weights = config.weights
        total_weight = sum(weights.get(r.rule_id, 1.0) for r in results)
        if total_weight == 0:
            return RuleResult(rule_id="fusion", direction="neutral", reason="加权投票: 权重全为0")

        vote = 0.0
        for r in results:
            w = weights.get(r.rule_id, 1.0)
            signal = _direction_signal(r.direction)
            vote += w * signal

        normalized = vote / total_weight

        if normalized >= config.buy_threshold:
            return RuleResult(
                rule_id="fusion", passed=True,
                score=abs(normalized),
                direction="buy",
                confidence=abs(normalized),
                reason=f"加权投票买入: vote={normalized:.4f} >= {config.buy_threshold}",
            )

        if normalized <= -config.sell_threshold:
            return RuleResult(
                rule_id="fusion", passed=True,
                score=abs(normalized),
                direction="sell",
                confidence=abs(normalized),
                reason=f"加权投票卖出: vote={normalized:.4f} <= -{config.sell_threshold}",
            )

        return RuleResult(
            rule_id="fusion", direction="neutral",
            reason=f"加权投票: vote={normalized:.4f} 未达阈值(±{config.buy_threshold})",
        )
