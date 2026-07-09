"""BIAS 乖离率反转规则插件 — SPI 机制

BIAS 乖离率衡量价格偏离均线的程度:
  BIAS = (close - MA) / MA * 100

经典反转信号:
  正乖离过大（close 远高于均线）→ 价格将回落，卖出
  负乖离过大（close 远低于均线）→ 价格将反弹，买入

阈值经验（A股，MA6）:
  极度超买: BIAS > 8 → 强卖出信号
  超买:     BIAS > 5 → 卖出信号
  极度超卖: BIAS < -8 → 强买入信号
  超卖:     BIAS < -5 → 买入信号

依赖因子: close, bias_6
前值因子: bias_6_prev（用于判断乖离率拐头）
"""
from ..core import RuleContext, RulePlugin, RuleResult


class BiasReversalPlugin(RulePlugin):
    """BIAS 乖离率反转规则插件

    买入条件: BIAS < -5（负乖离过大，超卖反弹）
    卖出条件: BIAS > 5（正乖离过大，超买回落）
    """

    rule_id: str = "ts_bias_reversal"
    name: str = "BIAS 乖离反转"
    factor_ids: list[str] = ["close", "bias_6"]
    prev_factor_ids: list[str] = ["bias_6"]

    def evaluate(self, context: RuleContext) -> RuleResult:
        fv = context.factor_values
        close = fv.get("close")
        bias = fv.get("bias_6")
        bias_prev = fv.get("bias_6_prev")

        if bias is None:
            return RuleResult(rule_id=self.rule_id, direction="neutral", reason="BIAS 数据不充分")

        # 极度超卖买入: BIAS < -8
        if bias < -8:
            prev_info = f", 前BIAS={bias_prev:.2f}" if bias_prev is not None else ""
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=1.0,
                direction="buy",
                confidence=0.9,
                reason=f"BIAS 极度超卖买入: BIAS={bias:.2f} < -8{prev_info}",
                detail={
                    "close": close, "bias_6": bias, "bias_6_prev": bias_prev,
                    "signal": "extreme_oversold",
                },
            )

        # 超卖买入: BIAS < -5
        if bias < -5:
            prev_info = f", 前BIAS={bias_prev:.2f}" if bias_prev is not None else ""
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=0.85,
                direction="buy",
                confidence=0.8,
                reason=f"BIAS 超卖买入: BIAS={bias:.2f} < -5{prev_info}",
                detail={
                    "close": close, "bias_6": bias, "bias_6_prev": bias_prev,
                    "signal": "oversold",
                },
            )

        # 极度超买卖出: BIAS > 8
        if bias > 8:
            prev_info = f", 前BIAS={bias_prev:.2f}" if bias_prev is not None else ""
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=1.0,
                direction="sell",
                confidence=0.9,
                reason=f"BIAS 极度超买卖出: BIAS={bias:.2f} > 8{prev_info}",
                detail={
                    "close": close, "bias_6": bias, "bias_6_prev": bias_prev,
                    "signal": "extreme_overbought",
                },
            )

        # 超买卖出: BIAS > 5
        if bias > 5:
            prev_info = f", 前BIAS={bias_prev:.2f}" if bias_prev is not None else ""
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=0.85,
                direction="sell",
                confidence=0.8,
                reason=f"BIAS 超买卖出: BIAS={bias:.2f} > 5{prev_info}",
                detail={
                    "close": close, "bias_6": bias, "bias_6_prev": bias_prev,
                    "signal": "overbought",
                },
            )

        # 乖离率拐头提示（不直接触发交易）
        if bias_prev is not None:
            if bias > 0 and bias < bias_prev:
                return RuleResult(
                    rule_id=self.rule_id,
                    direction="neutral",
                    reason=f"BIAS 正乖离回落: BIAS={bias:.2f} (前{bias_prev:.2f})",
                    detail={"close": close, "bias_6": bias, "bias_6_prev": bias_prev},
                )
            if bias < 0 and bias > bias_prev:
                return RuleResult(
                    rule_id=self.rule_id,
                    direction="neutral",
                    reason=f"BIAS 负乖离回升: BIAS={bias:.2f} (前{bias_prev:.2f})",
                    detail={"close": close, "bias_6": bias, "bias_6_prev": bias_prev},
                )

        return RuleResult(
            rule_id=self.rule_id,
            direction="neutral",
            reason=f"BIAS 无信号: BIAS={bias:.2f}",
            detail={"close": close, "bias_6": bias},
        )
