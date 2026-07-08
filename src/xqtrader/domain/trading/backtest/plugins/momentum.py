"""动量规则插件 — SPI 机制

动量策略是业界主流的趋势跟随策略:
  动量为正且增强 → 价格上涨动能增强，买入
  动量为负且增强 → 价格下跌动能增强，卖出

经典动量指标:
  mon_5d  = close / close.shift(5)  - 1  (5日动量)
  mon_10d = close / close.shift(10) - 1  (10日动量)
  mon_20d = close / close.shift(20) - 1  (20日动量)

信号:
  买入: mon_10d > 0 且 mon_10d > mon_10d_prev（动量向上加速）
  卖出: mon_10d < 0 且 mon_10d < mon_10d_prev（动量向下加速）

阈值过滤（避免噪声）:
  - 短期动量需 > 2% 才产生信号，避免微小波动触发
  - 中期动量（20日）作为趋势方向确认

依赖内置因子: close, mon_10d, mon_20d
前值因子: mon_10d（用于判断动量加速/减速）
"""
from ..core import RuleContext, RulePlugin, RuleResult


class MomentumPlugin(RulePlugin):
    """动量趋势跟随规则插件

    买入条件: mon_10d > 2% 且 mon_10d > mon_10d_prev（动量加速）
    卖出条件: mon_10d < -2% 且 mon_10d < mon_10d_prev（动量加速下跌）
    """

    rule_id: str = "ts_momentum"
    name: str = "动量趋势跟随"
    factor_ids: list[str] = ["close", "mon_10d", "mon_20d"]
    prev_factor_ids: list[str] = ["mon_10d"]

    # 动量阈值（百分比，小数形式）
    _MOM_THRESHOLD = 0.02

    def evaluate(self, context: RuleContext) -> RuleResult:
        fv = context.factor_values
        close = fv.get("close")
        mon_10d = fv.get("mon_10d")
        mon_20d = fv.get("mon_20d")
        mon_10d_prev = fv.get("mon_10d_prev")

        if mon_10d is None:
            return RuleResult(rule_id=self.rule_id, direction="neutral", reason="动量数据不充分")

        # 买入信号: mon_10d > 2% 且 mon_10d > mon_10d_prev（动量加速）
        if mon_10d > self._MOM_THRESHOLD:
            is_accelerating = mon_10d_prev is not None and mon_10d > mon_10d_prev
            # 中期趋势确认
            trend_confirm = mon_20d is not None and mon_20d > 0

            if is_accelerating:
                score = 1.0 if trend_confirm else 0.8
                confidence = 0.9 if trend_confirm else 0.75
                mon20_info = f", mon_20d={mon_20d:.4f}" if mon_20d is not None else ""
                prev_info = f", 前mon_10d={mon_10d_prev:.4f}" if mon_10d_prev is not None else ""
                return RuleResult(
                    rule_id=self.rule_id,
                    passed=True,
                    score=score,
                    direction="buy",
                    confidence=confidence,
                    reason=(
                        f"动量加速买入: mon_10d={mon_10d:.4f} > {self._MOM_THRESHOLD} "
                        f"且动量加速{prev_info}{mon20_info}"
                    ),
                    detail={
                        "close": close, "mon_10d": mon_10d, "mon_20d": mon_20d,
                        "mon_10d_prev": mon_10d_prev,
                        "signal": "momentum_accel_up",
                    },
                )

        # 卖出信号: mon_10d < -2% 且 mon_10d < mon_10d_prev（动量加速下跌）
        if mon_10d < -self._MOM_THRESHOLD:
            is_decelerating = mon_10d_prev is not None and mon_10d < mon_10d_prev
            trend_confirm = mon_20d is not None and mon_20d < 0

            if is_decelerating:
                score = 1.0 if trend_confirm else 0.8
                confidence = 0.9 if trend_confirm else 0.75
                mon20_info = f", mon_20d={mon_20d:.4f}" if mon_20d is not None else ""
                prev_info = f", 前mon_10d={mon_10d_prev:.4f}" if mon_10d_prev is not None else ""
                return RuleResult(
                    rule_id=self.rule_id,
                    passed=True,
                    score=score,
                    direction="sell",
                    confidence=confidence,
                    reason=(
                        f"动量加速下跌卖出: mon_10d={mon_10d:.4f} < -{self._MOM_THRESHOLD} "
                        f"且动量加速下跌{prev_info}{mon20_info}"
                    ),
                    detail={
                        "close": close, "mon_10d": mon_10d, "mon_20d": mon_20d,
                        "mon_10d_prev": mon_10d_prev,
                        "signal": "momentum_accel_down",
                    },
                )

        # 动量反转提示（不直接触发交易）
        if mon_10d_prev is not None:
            # 动量由正转负
            if mon_10d_prev > 0 and mon_10d < 0:
                return RuleResult(
                    rule_id=self.rule_id,
                    direction="neutral",
                    reason=(
                        f"动量反转预警: mon_10d 由正转负 "
                        f"({mon_10d_prev:.4f} → {mon_10d:.4f})"
                    ),
                    detail={
                        "close": close, "mon_10d": mon_10d, "mon_20d": mon_20d,
                        "mon_10d_prev": mon_10d_prev,
                    },
                )
            # 动量由负转正
            if mon_10d_prev < 0 and mon_10d > 0:
                return RuleResult(
                    rule_id=self.rule_id,
                    direction="neutral",
                    reason=(
                        f"动量反转预警: mon_10d 由负转正 "
                        f"({mon_10d_prev:.4f} → {mon_10d:.4f})"
                    ),
                    detail={
                        "close": close, "mon_10d": mon_10d, "mon_20d": mon_20d,
                        "mon_10d_prev": mon_10d_prev,
                    },
                )

        return RuleResult(
            rule_id=self.rule_id,
            direction="neutral",
            reason=(
                f"动量无信号: mon_10d={mon_10d:.4f}"
                + (f", mon_20d={mon_20d:.4f}" if mon_20d is not None else "")
            ),
            detail={"close": close, "mon_10d": mon_10d, "mon_20d": mon_20d},
        )
