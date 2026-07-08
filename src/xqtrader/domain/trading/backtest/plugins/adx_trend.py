"""ADX 趋势强度规则插件 — SPI 机制

ADX (Average Directional Index) 衡量趋势强度（不区分方向）:
  ADX < 20: 无趋势（震荡市）
  ADX 20~25: 趋势形成中
  ADX 25~50: 强趋势
  ADX > 50: 极强趋势

DI+/DI- 用于判断趋势方向:
  +DI > -DI: 多头趋势
  -DI > +DI: 空头趋势

信号:
  买入: ADX > 25 且 +DI 上穿 -DI（多头趋势形成）
  卖出: ADX > 25 且 -DI 上穿 +DI（空头趋势形成）
  或简化版: ADX > 25 且 +DI > -DI 买入, ADX > 25 且 -DI > +DI 卖出

依赖内置因子: adx, adx_plus_di, adx_minus_di
前值因子: adx_plus_di, adx_minus_di（用于判断穿越）
"""
from ..core import RuleContext, RulePlugin, RuleResult


class ADXTrendPlugin(RulePlugin):
    """ADX 趋势强度规则插件

    买入条件: ADX > 25（趋势确立）且 +DI 上穿 -DI（多头转向）
    卖出条件: ADX > 25（趋势确立）且 -DI 上穿 +DI（空头转向）
    """

    rule_id: str = "ts_adx_trend"
    name: str = "ADX 趋势强度"
    factor_ids: list[str] = ["adx", "adx_plus_di", "adx_minus_di"]
    prev_factor_ids: list[str] = ["adx_plus_di", "adx_minus_di"]

    def evaluate(self, context: RuleContext) -> RuleResult:
        fv = context.factor_values
        adx = fv.get("adx")
        plus_di = fv.get("adx_plus_di")
        minus_di = fv.get("adx_minus_di")
        plus_di_prev = fv.get("adx_plus_di_prev")
        minus_di_prev = fv.get("adx_minus_di_prev")

        if adx is None or plus_di is None or minus_di is None:
            return RuleResult(rule_id=self.rule_id, direction="neutral", reason="ADX 数据不充分")
        if plus_di_prev is None or minus_di_prev is None:
            return RuleResult(rule_id=self.rule_id, direction="neutral", reason="ADX 前值数据不充分")

        # 趋势强度判断
        is_trending = adx > 25
        # +DI 上穿 -DI（多头转向）
        is_bullish_cross = plus_di_prev <= minus_di_prev and plus_di > minus_di
        # -DI 上穿 +DI（空头转向）
        is_bearish_cross = minus_di_prev <= plus_di_prev and minus_di > plus_di

        # 买入信号: ADX > 25 且 +DI 上穿 -DI
        if is_trending and is_bullish_cross:
            confidence = 0.9 if adx > 30 else 0.8
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=1.0 if adx > 30 else 0.85,
                direction="buy",
                confidence=confidence,
                reason=(
                    f"ADX 多头趋势买入: ADX={adx:.2f} > 25, "
                    f"+DI={plus_di:.2f} 上穿 -DI={minus_di:.2f} "
                    f"(前+DI={plus_di_prev:.2f}, 前-DI={minus_di_prev:.2f})"
                ),
                detail={
                    "adx": adx, "adx_plus_di": plus_di, "adx_minus_di": minus_di,
                    "adx_plus_di_prev": plus_di_prev, "adx_minus_di_prev": minus_di_prev,
                    "signal": "bullish_trend_cross",
                },
            )

        # 卖出信号: ADX > 25 且 -DI 上穿 +DI
        if is_trending and is_bearish_cross:
            confidence = 0.9 if adx > 30 else 0.8
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=1.0 if adx > 30 else 0.85,
                direction="sell",
                confidence=confidence,
                reason=(
                    f"ADX 空头趋势卖出: ADX={adx:.2f} > 25, "
                    f"-DI={minus_di:.2f} 上穿 +DI={plus_di:.2f} "
                    f"(前+DI={plus_di_prev:.2f}, 前-DI={minus_di_prev:.2f})"
                ),
                detail={
                    "adx": adx, "adx_plus_di": plus_di, "adx_minus_di": minus_di,
                    "adx_plus_di_prev": plus_di_prev, "adx_minus_di_prev": minus_di_prev,
                    "signal": "bearish_trend_cross",
                },
            )

        # 趋势中持有提示（不直接触发交易）
        if is_trending:
            if plus_di > minus_di:
                return RuleResult(
                    rule_id=self.rule_id,
                    direction="neutral",
                    reason=(
                        f"ADX 多头趋势持续: ADX={adx:.2f}, +DI={plus_di:.2f} > -DI={minus_di:.2f}"
                    ),
                    detail={"adx": adx, "adx_plus_di": plus_di, "adx_minus_di": minus_di},
                )
            return RuleResult(
                rule_id=self.rule_id,
                direction="neutral",
                reason=(
                    f"ADX 空头趋势持续: ADX={adx:.2f}, -DI={minus_di:.2f} > +DI={plus_di:.2f}"
                ),
                detail={"adx": adx, "adx_plus_di": plus_di, "adx_minus_di": minus_di},
            )

        return RuleResult(
            rule_id=self.rule_id,
            direction="neutral",
            reason=f"ADX 无趋势: ADX={adx:.2f} < 25（震荡市）",
            detail={"adx": adx, "adx_plus_di": plus_di, "adx_minus_di": minus_di},
        )
