"""唐奇通道/海龟趋势突破规则插件。"""

from ..core import RuleContext, RulePlugin, RuleResult


class DonchianTurtlePlugin(RulePlugin):
    """基于唐奇通道的海龟趋势突破规则。"""

    rule_id: str = "ts_donchian_turtle"
    name: str = "海龟唐奇通道突破"
    factor_ids: list[str] = ["close", "donchian_high_20", "donchian_low_10", "atr_14"]
    prev_factor_ids: list[str] = []

    def evaluate(self, context: RuleContext) -> RuleResult:
        fv = context.factor_values
        close = fv.get("close")
        high_breakout = fv.get("donchian_high_20")
        exit_low = fv.get("donchian_low_10")
        atr = fv.get("atr_14")
        if close is None or high_breakout is None or exit_low is None:
            return RuleResult(rule_id=self.rule_id, direction="neutral", reason="唐奇通道数据不充分")

        if close >= high_breakout:
            strength = self._breakout_strength(close, high_breakout, atr)
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=strength,
                direction="buy",
                confidence=max(0.72, min(0.92, strength)),
                reason=(
                    f"海龟突破买入: close={close:.4f} 上破20日唐奇上轨={high_breakout:.4f}, "
                    f"ATR14={atr:.4f}" if atr is not None else
                    f"海龟突破买入: close={close:.4f} 上破20日唐奇上轨={high_breakout:.4f}"
                ),
                detail={
                    "close": close,
                    "donchian_high_20": high_breakout,
                    "donchian_low_10": exit_low,
                    "atr_14": atr,
                    "system": "turtle_donchian_20_10",
                },
            )

        if close <= exit_low:
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=0.8,
                direction="sell",
                confidence=0.78,
                reason=f"海龟退出卖出: close={close:.4f} 跌破10日唐奇下轨={exit_low:.4f}",
                detail={
                    "close": close,
                    "donchian_high_20": high_breakout,
                    "donchian_low_10": exit_low,
                    "atr_14": atr,
                    "system": "turtle_donchian_20_10",
                },
            )

        return RuleResult(
            rule_id=self.rule_id,
            direction="neutral",
            reason=(
                f"未突破唐奇通道: close={close:.4f}, "
                f"上轨={high_breakout:.4f}, 退出下轨={exit_low:.4f}"
            ),
            detail={
                "close": close,
                "donchian_high_20": high_breakout,
                "donchian_low_10": exit_low,
                "atr_14": atr,
                "system": "turtle_donchian_20_10",
            },
        )

    @staticmethod
    def _breakout_strength(close: float, high_breakout: float, atr: float | None) -> float:
        if atr is None or atr <= 0:
            return 0.75
        return max(0.75, min(1.0, 0.75 + ((close - high_breakout) / atr) * 0.25))
