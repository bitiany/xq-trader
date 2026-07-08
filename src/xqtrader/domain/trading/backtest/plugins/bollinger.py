"""布林带突破规则插件 — SPI 机制

布林带计算:
  middle = SMA(close, 20)
  upper = middle + 2 * std(close, 20)
  lower = middle - 2 * std(close, 20)

信号:
  突破上轨买入: close_prev <= upper_prev and close > upper（突破上轨）
  跌破下轨卖出: close_prev >= lower_prev and close < lower（跌破下轨）
  布林带收窄后突破更有效（band_width < 某阈值）

依赖内置因子: close, boll_upper, boll_middle, boll_lower, boll_width
前值因子: close_prev（用于判断突破）, boll_upper_prev, boll_lower_prev
"""
from ..core import RuleContext, RulePlugin, RuleResult


class BollingerPlugin(RulePlugin):
    """布林带突破规则插件

    买入条件: close 从下方突破上轨
    卖出条件: close 从上方跌破下轨
    辅助判断: 布林带宽度收窄时突破信号更可靠
    """

    rule_id: str = "ts_bollinger_break"
    name: str = "布林带突破"
    factor_ids: list[str] = ["close", "boll_upper", "boll_middle", "boll_lower", "boll_width"]
    prev_factor_ids: list[str] = ["close", "boll_upper", "boll_lower"]

    def evaluate(self, context: RuleContext) -> RuleResult:
        fv = context.factor_values
        close = fv.get("close")
        upper = fv.get("boll_upper")
        middle = fv.get("boll_middle")
        lower = fv.get("boll_lower")
        width = fv.get("boll_width")
        close_prev = fv.get("close_prev")
        upper_prev = fv.get("boll_upper_prev")
        lower_prev = fv.get("boll_lower_prev")

        if close is None or upper is None or lower is None:
            return RuleResult(rule_id=self.rule_id, direction="neutral", reason="布林带数据不充分")
        if close_prev is None or upper_prev is None or lower_prev is None:
            return RuleResult(rule_id=self.rule_id, direction="neutral", reason="布林带前值数据不充分")

        # 突破上轨: 前close <= 前upper 且 当前close > 当前upper
        is_break_up = close_prev <= upper_prev and close > upper
        # 跌破下轨: 前close >= 前lower 且 当前close < 当前lower
        is_break_down = close_prev >= lower_prev and close < lower

        # 布林带宽度收窄（收窄后突破信号更可靠）
        is_squeeze = width is not None and width < 0.1

        # 买入信号: 突破上轨
        if is_break_up:
            confidence = 0.85 if is_squeeze else 0.75
            squeeze_hint = "（布林带收窄，突破信号强）" if is_squeeze else ""
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=1.0 if is_squeeze else 0.85,
                direction="buy",
                confidence=confidence,
                reason=(
                    f"布林带突破上轨买入: close={close:.4f} > upper={upper:.4f} "
                    f"(前close={close_prev:.4f}, 前upper={upper_prev:.4f}){squeeze_hint}"
                ),
                detail={
                    "close": close, "boll_upper": upper, "boll_middle": middle,
                    "boll_lower": lower, "boll_width": width,
                    "signal": "break_up" + ("_squeeze" if is_squeeze else ""),
                },
            )

        # 卖出信号: 跌破下轨
        if is_break_down:
            confidence = 0.85 if is_squeeze else 0.75
            squeeze_hint = "（布林带收窄，突破信号强）" if is_squeeze else ""
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=1.0 if is_squeeze else 0.85,
                direction="sell",
                confidence=confidence,
                reason=(
                    f"布林带跌破下轨卖出: close={close:.4f} < lower={lower:.4f} "
                    f"(前close={close_prev:.4f}, 前lower={lower_prev:.4f}){squeeze_hint}"
                ),
                detail={
                    "close": close, "boll_upper": upper, "boll_middle": middle,
                    "boll_lower": lower, "boll_width": width,
                    "signal": "break_down" + ("_squeeze" if is_squeeze else ""),
                },
            )

        # 均值回归提示（不直接触发交易）
        if middle is not None:
            if close < lower:
                return RuleResult(
                    rule_id=self.rule_id,
                    direction="neutral",
                    reason=f"布林带低位预警: close={close:.4f} < lower={lower:.4f}（等待突破确认）",
                    detail={"close": close, "boll_lower": lower, "boll_middle": middle},
                )
            if close > upper:
                return RuleResult(
                    rule_id=self.rule_id,
                    direction="neutral",
                    reason=f"布林带高位预警: close={close:.4f} > upper={upper:.4f}（等待跌破确认）",
                    detail={"close": close, "boll_upper": upper, "boll_middle": middle},
                )

        return RuleResult(
            rule_id=self.rule_id,
            direction="neutral",
            reason=(
                f"布林带无信号: close={close:.4f}, "
                f"upper={upper:.4f}, lower={lower:.4f}"
                + (f", width={width:.4f}" if width is not None else "")
            ),
            detail={
                "close": close, "boll_upper": upper, "boll_lower": lower,
                "boll_width": width,
            },
        )
