"""IC 加权融合策略 — 用历史 IC（信息系数）值作为权重"""

from ..core import FusionConfig, RuleResult
from .base import FusionStrategy
from .weighted import _direction_signal


class ICWeightedFusion(FusionStrategy):
    """IC 加权融合 — 用历史 IC 值作为权重的加权评分

    公式:
      ic_score = Σ(IC_i × score_i × signal_i) / Σ|IC_i|
      signal_i = +1 (buy) / -1 (sell) / 0 (neutral)

    与加权评分的区别:
      - 权重来自历史 IC 值（可正可负），而非手动指定
      - 分母用 Σ|IC_i| 而非 Σ(IC_i)，保证结果在 [-1, 1] 范围内
      - IC 为负的规则会反向贡献（IC<0 的规则 buy 信号会拉低总分）

    使用场景:
      - 规则/因子有历史 IC 数据时使用
      - weights 的 value 为该规则的历史 IC 均值
    """

    def fuse(self, results: list[RuleResult], config: FusionConfig) -> RuleResult:
        if not results:
            return RuleResult(rule_id="fusion", direction="neutral", reason="IC加权: 无规则结果")

        ic_weights = config.weights
        total_ic = sum(abs(ic_weights.get(r.rule_id, 0.0)) for r in results)
        if total_ic == 0:
            return RuleResult(rule_id="fusion", direction="neutral", reason="IC加权: IC权重全为0")

        ic_score = 0.0
        for r in results:
            ic = ic_weights.get(r.rule_id, 0.0)
            signal = _direction_signal(r.direction)
            ic_score += ic * r.score * signal

        normalized = ic_score / total_ic

        if normalized >= config.buy_threshold:
            return RuleResult(
                rule_id="fusion", passed=True,
                score=abs(normalized),
                direction="buy",
                confidence=abs(normalized),
                reason=f"IC加权买入: score={normalized:.4f} >= {config.buy_threshold}",
            )

        if normalized <= -config.sell_threshold:
            return RuleResult(
                rule_id="fusion", passed=True,
                score=abs(normalized),
                direction="sell",
                confidence=abs(normalized),
                reason=f"IC加权卖出: score={normalized:.4f} <= -{config.sell_threshold}",
            )

        return RuleResult(
            rule_id="fusion", direction="neutral",
            reason=f"IC加权: score={normalized:.4f} 未达阈值(±{config.buy_threshold})",
        )
