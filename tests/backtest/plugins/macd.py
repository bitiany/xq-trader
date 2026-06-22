"""MACD 规则插件 — 自定义插件

基于 hist 柱的斜率法和面积法产生买卖信号。

买入条件（满足任一）：
  1. 金叉：hist 由负转正，动能方向反转向上
  2. 红柱扩张+面积放大：hist > 0 且 hist_slope > 0 且 hist_area 递增

卖出条件（满足任一）：
  1. 死叉：hist 由正转负，动能方向反转向下
  2. 绿柱扩张+面积放大：hist < 0 且 hist_slope < 0 且 hist_area 递减
"""

from ..core import RuleContext, RuleResult, RulePlugin


class MACDPlugin(RulePlugin):
    """MACD 规则插件"""

    rule_id: str = "macd"
    name: str = "MACD 规则"
    factor_ids: list[str] = ["macd", "signal", "hist", "hist_slope", "hist_area"]
    prev_factor_ids: list[str] = ["hist", "hist_area"]

    def evaluate(self, context: RuleContext) -> RuleResult:
        fv = context.factor_values
        hist = fv.get("hist")
        hist_prev = fv.get("hist_prev")
        hist_slope = fv.get("hist_slope")
        hist_area = fv.get("hist_area")
        hist_area_prev = fv.get("hist_area_prev")
        macd_val = fv.get("macd")
        signal_val = fv.get("signal")

        if hist is None or hist_prev is None or hist_slope is None:
            return RuleResult(rule_id=self.rule_id, direction="neutral", reason="指标数据不充分")

        # ── 买入信号 ──
        if hist_prev <= 0 and hist > 0:
            return RuleResult(
                rule_id=self.rule_id, passed=True, score=1.0, direction="buy", confidence=0.9,
                reason=f"金叉买入: hist由负转正 (hist: {hist_prev:.4f}→{hist:.4f}, "
                       f"hist_slope={hist_slope:.4f}, MACD={macd_val:.4f}, Signal={signal_val:.4f})",
                detail={"hist_prev": hist_prev, "hist": hist, "hist_slope": hist_slope,
                        "macd": macd_val, "signal": signal_val},
            )

        if hist > 0 and hist_slope > 0 and hist_area is not None and hist_area_prev is not None and hist_area > hist_area_prev:
            return RuleResult(
                rule_id=self.rule_id, passed=True, score=0.7, direction="buy", confidence=0.7,
                reason=f"红柱扩张买入: hist={hist:.4f}, hist_slope={hist_slope:.4f}>0, "
                       f"面积放大({hist_area_prev:.4f}→{hist_area:.4f})",
                detail={"hist": hist, "hist_slope": hist_slope,
                        "hist_area": hist_area, "hist_area_prev": hist_area_prev},
            )

        # ── 卖出信号 ──
        if hist_prev >= 0 and hist < 0:
            return RuleResult(
                rule_id=self.rule_id, passed=True, score=1.0, direction="sell", confidence=0.9,
                reason=f"死叉卖出: hist由正转负 (hist: {hist_prev:.4f}→{hist:.4f}, "
                       f"hist_slope={hist_slope:.4f}, MACD={macd_val:.4f}, Signal={signal_val:.4f})",
                detail={"hist_prev": hist_prev, "hist": hist, "hist_slope": hist_slope,
                        "macd": macd_val, "signal": signal_val},
            )

        if hist < 0 and hist_slope < 0 and hist_area is not None and hist_area_prev is not None:
            if hist_area < hist_area_prev:
                return RuleResult(
                    rule_id=self.rule_id, passed=True, score=0.7, direction="sell", confidence=0.7,
                    reason=f"绿柱扩张卖出: hist={hist:.4f}, hist_slope={hist_slope:.4f}<0, "
                           f"面积放大({hist_area_prev:.4f}→{hist_area:.4f})",
                    detail={"hist": hist, "hist_slope": hist_slope,
                            "hist_area": hist_area, "hist_area_prev": hist_area_prev},
                )

        return RuleResult(rule_id=self.rule_id, direction="neutral", reason="无信号")
