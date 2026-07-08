"""RSI 背离 + 超买超卖规则插件 — SPI 机制

RSI 背离是经典的反转信号:
  顶背离: 价格创新高，但 RSI 未创新高（动能减弱，看跌）
  底背离: 价格创新低，但 RSI 未创新低（动能增强，看涨）

超买超卖是 RSI 基础信号:
  超卖买入: RSI < 30（市场过度悲观，反弹在即）
  超买卖出: RSI > 70（市场过度乐观，回调在即）

背离和超买超卖判断都需要时序数据，表达式无法实现，必须用 SPI 机制。

依赖内置因子: close, rsi
前值因子: close_prev, rsi_prev（用于判断是否突破前高/前低）
"""
from ..core import RuleContext, RulePlugin, RuleResult


class RSIDivergencePlugin(RulePlugin):
    """RSI 背离 + 超买超卖规则插件

    买入条件（任一满足）:
      1. 超卖反弹: RSI < 40（市场偏悲观，反弹在即）
      2. 底背离: close 下跌但 RSI 上升（动能增强）

    卖出条件（任一满足）:
      1. 超买回落: RSI > 60（市场偏乐观，回调在即）
      2. 顶背离: close 上涨但 RSI 下降（动能减弱）
    """

    rule_id: str = "ts_rsi_divergence"
    name: str = "RSI 背离超买超卖"
    factor_ids: list[str] = ["close", "rsi"]
    prev_factor_ids: list[str] = ["close", "rsi"]

    def evaluate(self, context: RuleContext) -> RuleResult:
        fv = context.factor_values
        close = fv.get("close")
        rsi = fv.get("rsi")
        close_prev = fv.get("close_prev")
        rsi_prev = fv.get("rsi_prev")

        if close is None or rsi is None:
            return RuleResult(rule_id=self.rule_id, direction="neutral", reason="RSI 数据不充分")

        # 1. 超卖买入: RSI < 40
        if rsi < 40:
            prev_info = f", 前RSI={rsi_prev:.2f}" if rsi_prev is not None else ""
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=1.0,
                direction="buy",
                confidence=0.85,
                reason=f"RSI 超卖买入: RSI={rsi:.2f} < 40{prev_info}",
                detail={
                    "close": close, "rsi": rsi,
                    "close_prev": close_prev, "rsi_prev": rsi_prev,
                    "signal": "oversold",
                },
            )

        # 2. 超买卖出: RSI > 60
        if rsi > 60:
            prev_info = f", 前RSI={rsi_prev:.2f}" if rsi_prev is not None else ""
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=1.0,
                direction="sell",
                confidence=0.85,
                reason=f"RSI 超买卖出: RSI={rsi:.2f} > 60{prev_info}",
                detail={
                    "close": close, "rsi": rsi,
                    "close_prev": close_prev, "rsi_prev": rsi_prev,
                    "signal": "overbought",
                },
            )

        # 3. 底背离: close 下跌但 RSI 上升（需要前值数据）
        if close_prev is not None and rsi_prev is not None:
            is_bullish_divergence = close < close_prev and rsi > rsi_prev and rsi < 50
            if is_bullish_divergence:
                return RuleResult(
                    rule_id=self.rule_id,
                    passed=True,
                    score=0.8,
                    direction="buy",
                    confidence=0.75,
                    reason=(
                        f"RSI 底背离买入: close={close:.4f} 下跌但 RSI={rsi:.2f} 上升 "
                        f"(前close={close_prev:.4f}, 前RSI={rsi_prev:.2f})"
                    ),
                    detail={
                        "close": close, "rsi": rsi,
                        "close_prev": close_prev, "rsi_prev": rsi_prev,
                        "signal": "bullish_divergence",
                    },
                )

            # 4. 顶背离: close 上涨但 RSI 下降
            is_bearish_divergence = close > close_prev and rsi < rsi_prev and rsi > 50
            if is_bearish_divergence:
                return RuleResult(
                    rule_id=self.rule_id,
                    passed=True,
                    score=0.8,
                    direction="sell",
                    confidence=0.75,
                    reason=(
                        f"RSI 顶背离卖出: close={close:.4f} 上涨但 RSI={rsi:.2f} 下降 "
                        f"(前close={close_prev:.4f}, 前RSI={rsi_prev:.2f})"
                    ),
                    detail={
                        "close": close, "rsi": rsi,
                        "close_prev": close_prev, "rsi_prev": rsi_prev,
                        "signal": "bearish_divergence",
                    },
                )

        prev_info = f", 前RSI={rsi_prev:.2f}" if rsi_prev is not None else ""
        return RuleResult(
            rule_id=self.rule_id,
            direction="neutral",
            reason=f"RSI 无信号: RSI={rsi:.2f}{prev_info}",
            detail={
                "close": close, "rsi": rsi,
                "close_prev": close_prev, "rsi_prev": rsi_prev,
            },
        )
