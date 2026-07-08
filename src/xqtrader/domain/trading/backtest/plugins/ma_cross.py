"""均线交叉规则插件 — SPI 机制

经典双均线交叉策略:
  金叉买入: 短期均线从下方上穿长期均线
  死叉卖出: 短期均线从上方下穿长期均线

依赖内置因子: ma_short, ma_long
前值因子: ma_short_prev, ma_long_prev
"""
from ..core import RuleContext, RulePlugin, RuleResult


class MACrossPlugin(RulePlugin):
    """双均线交叉规则插件

    买入条件: ma_short 上穿 ma_long（金叉）
    卖出条件: ma_short 下穿 ma_long（死叉）
    """

    rule_id: str = "ts_ma_cross"
    name: str = "双均线交叉"
    factor_ids: list[str] = ["ma_short", "ma_long"]
    prev_factor_ids: list[str] = ["ma_short", "ma_long"]

    def evaluate(self, context: RuleContext) -> RuleResult:
        fv = context.factor_values
        ma_short = fv.get("ma_short")
        ma_long = fv.get("ma_long")
        ma_short_prev = fv.get("ma_short_prev")
        ma_long_prev = fv.get("ma_long_prev")

        if ma_short is None or ma_long is None:
            return RuleResult(rule_id=self.rule_id, direction="neutral", reason="均线数据不充分")
        if ma_short_prev is None or ma_long_prev is None:
            return RuleResult(rule_id=self.rule_id, direction="neutral", reason="均线前值数据不充分")

        # 金叉: 短期均线从下方上穿长期均线
        is_golden_cross = ma_short_prev <= ma_long_prev and ma_short > ma_long
        # 死叉: 短期均线从上方下穿长期均线
        is_dead_cross = ma_short_prev >= ma_long_prev and ma_short < ma_long

        if is_golden_cross:
            # 计算均线距离（突破强度）
            spread = (ma_short - ma_long) / ma_long * 100 if ma_long > 0 else 0
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=1.0,
                direction="buy",
                confidence=0.85,
                reason=(
                    f"均线金叉买入: ma_short={ma_short:.4f} 上穿 ma_long={ma_long:.4f} "
                    f"(前ma_short={ma_short_prev:.4f}, 前ma_long={ma_long_prev:.4f}, "
                    f"spread={spread:.2f}%)"
                ),
                detail={
                    "ma_short": ma_short, "ma_long": ma_long,
                    "ma_short_prev": ma_short_prev, "ma_long_prev": ma_long_prev,
                    "spread_pct": spread,
                    "signal": "golden_cross",
                },
            )

        if is_dead_cross:
            spread = (ma_short - ma_long) / ma_long * 100 if ma_long > 0 else 0
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=1.0,
                direction="sell",
                confidence=0.85,
                reason=(
                    f"均线死叉卖出: ma_short={ma_short:.4f} 下穿 ma_long={ma_long:.4f} "
                    f"(前ma_short={ma_short_prev:.4f}, 前ma_long={ma_long_prev:.4f}, "
                    f"spread={spread:.2f}%)"
                ),
                detail={
                    "ma_short": ma_short, "ma_long": ma_long,
                    "ma_short_prev": ma_short_prev, "ma_long_prev": ma_long_prev,
                    "spread_pct": spread,
                    "signal": "dead_cross",
                },
            )

        spread = (ma_short - ma_long) / ma_long * 100 if ma_long > 0 else 0.0
        return RuleResult(
            rule_id=self.rule_id,
            direction="neutral",
            reason=(
                f"均线无信号: ma_short={ma_short:.4f}, ma_long={ma_long:.4f}, "
                f"spread={spread:.2f}%"
            ),
            detail={"ma_short": ma_short, "ma_long": ma_long, "spread_pct": spread},
        )
