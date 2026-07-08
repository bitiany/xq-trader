"""KDJ 金叉死叉规则插件 — SPI 机制

KDJ 指标计算:
  RSV = (close - lowest_low_n) / (highest_high_n - lowest_low_n) * 100
  K = EMA(RSV, 3)  （国内主流实现：K = 前K×2/3 + RSV×1/3）
  D = EMA(K, 3)    （D = 前D×2/3 + K×1/3）
  J = 3*K - 2*D

信号:
  金叉买入: K_prev <= D_prev and K > D and K < 50（低位金叉）
  死叉卖出: K_prev >= D_prev and K < D and K > 50（高位死叉）
  超买超卖辅助: J > 100 超买（卖出预警），J < 0 超卖（买入预警）

依赖内置因子: kdj_k, kdj_d, kdj_j
前值因子: kdj_k_prev, kdj_d_prev
"""
from ..core import RuleContext, RulePlugin, RuleResult


class KDJPlugin(RulePlugin):
    """KDJ 金叉死叉规则插件

    买入条件: K 上穿 D（金叉）且 K < 50（低位金叉更可靠）
    卖出条件: K 下穿 D（死叉）且 K > 50（高位死叉更可靠）
    """

    rule_id: str = "ts_kdj_cross"
    name: str = "KDJ 金叉死叉"
    factor_ids: list[str] = ["kdj_k", "kdj_d", "kdj_j"]
    prev_factor_ids: list[str] = ["kdj_k", "kdj_d"]

    def evaluate(self, context: RuleContext) -> RuleResult:
        fv = context.factor_values
        k = fv.get("kdj_k")
        d = fv.get("kdj_d")
        j = fv.get("kdj_j")
        k_prev = fv.get("kdj_k_prev")
        d_prev = fv.get("kdj_d_prev")

        if k is None or d is None or k_prev is None or d_prev is None:
            return RuleResult(rule_id=self.rule_id, direction="neutral", reason="KDJ 数据不充分")

        # 金叉: K 从下方上穿 D（前K<=前D 且 当前K>D）
        is_golden_cross = k_prev <= d_prev and k > d
        # 死叉: K 从上方下穿 D（前K>=前D 且 当前K<D）
        is_dead_cross = k_prev >= d_prev and k < d

        # 买入信号: 低位金叉
        if is_golden_cross and k < 50:
            confidence = 0.9 if k < 30 else 0.75
            j_info = f", J={j:.2f}" if j is not None else ""
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=1.0,
                direction="buy",
                confidence=confidence,
                reason=(
                    f"KDJ 低位金叉买入: K={k:.2f} 上穿 D={d:.2f} "
                    f"(前K={k_prev:.2f}, 前D={d_prev:.2f}{j_info})"
                ),
                detail={
                    "kdj_k": k, "kdj_d": d, "kdj_j": j,
                    "kdj_k_prev": k_prev, "kdj_d_prev": d_prev,
                    "signal": "golden_cross_low",
                },
            )

        # 卖出信号: 高位死叉
        if is_dead_cross and k > 50:
            confidence = 0.9 if k > 70 else 0.75
            j_info = f", J={j:.2f}" if j is not None else ""
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                score=1.0,
                direction="sell",
                confidence=confidence,
                reason=(
                    f"KDJ 高位死叉卖出: K={k:.2f} 下穿 D={d:.2f} "
                    f"(前K={k_prev:.2f}, 前D={d_prev:.2f}{j_info})"
                ),
                detail={
                    "kdj_k": k, "kdj_d": d, "kdj_j": j,
                    "kdj_k_prev": k_prev, "kdj_d_prev": d_prev,
                    "signal": "dead_cross_high",
                },
            )

        # J 值超买超卖辅助提示（不直接触发交易）
        if j is not None and j > 100:
            return RuleResult(
                rule_id=self.rule_id,
                direction="neutral",
                reason=f"KDJ 超买预警: J={j:.2f} > 100（等待死叉）",
                detail={"kdj_k": k, "kdj_d": d, "kdj_j": j},
            )

        if j is not None and j < 0:
            return RuleResult(
                rule_id=self.rule_id,
                direction="neutral",
                reason=f"KDJ 超卖预警: J={j:.2f} < 0（等待金叉）",
                detail={"kdj_k": k, "kdj_d": d, "kdj_j": j},
            )

        if j is not None:
            reason = f"KDJ 无信号: K={k:.2f}, D={d:.2f}, J={j:.2f}"
        else:
            reason = f"KDJ 无信号: K={k:.2f}, D={d:.2f}"
        return RuleResult(
            rule_id=self.rule_id,
            direction="neutral",
            reason=reason,
            detail={"kdj_k": k, "kdj_d": d, "kdj_j": j},
        )
