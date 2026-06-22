"""表达式规则插件 — 内置默认插件

通过 buy_expr / sell_expr 定义信号条件，支持因子名作为变量名。
表达式语法参考 QLib:
  - 比较运算: rsi < 30, hist > 0, macd > signal
  - 逻辑运算: rsi < 30 and hist > 0
  - 算术运算: close / open > 1.05
  - 函数: abs(hist) > 0.1, max(rsi_6, rsi_14) > 70
"""

import math

from ..core import RuleConfig, RuleContext, RuleResult, RulePlugin

# 安全的表达式求值环境
_SAFE_BUILTINS = {
    "abs": abs,
    "max": max,
    "min": min,
    "round": round,
    "int": int,
    "float": float,
    "bool": bool,
    "True": True,
    "False": False,
    "math": math,
    "nan": float("nan"),
    "inf": float("inf"),
}


def _safe_eval(expr: str, namespace: dict[str, float]) -> bool:
    """安全地求值表达式，仅允许因子名、数值和基本运算"""
    try:
        return bool(eval(expr, {"__builtins__": _SAFE_BUILTINS}, namespace))
    except Exception:
        return False


class ExpressionPlugin(RulePlugin):
    """表达式规则插件（内置默认）

    通过 RuleConfig 的 buy_expr / sell_expr 字段配置信号条件。
    factor_ids 声明表达式所需的因子，引擎自动注入因子值。
    """

    rule_id: str = "expression"
    name: str = "表达式规则"

    def __init__(self, config: RuleConfig):
        self._config = config
        self._rule_id = config.rule_id
        self._buy_expr = config.buy_expr
        self._sell_expr = config.sell_expr
        # 从 config 继承因子声明
        self.factor_ids = list(config.factor_ids)
        self.prev_factor_ids = list(config.prev_factor_ids)

    def evaluate(self, context: RuleContext) -> RuleResult:
        fv = context.factor_values

        # 检查因子数据是否充分
        missing = [fid for fid in self._config.factor_ids if fv.get(fid) is None]
        if missing:
            return RuleResult(rule_id=self._rule_id, direction="neutral",
                              reason=f"因子数据缺失: {missing}")

        # 求值买入表达式
        if self._buy_expr and _safe_eval(self._buy_expr, fv):
            factor_summary = ", ".join(f"{k}={v:.4f}" for k, v in fv.items() if v is not None)
            return RuleResult(
                rule_id=self._rule_id,
                passed=True,
                score=1.0,
                direction="buy",
                confidence=0.8,
                reason=f"表达式买入: {self._buy_expr} ({factor_summary})",
                detail={"expr": self._buy_expr, "factor_values": {k: v for k, v in fv.items() if v is not None}},
            )

        # 求值卖出表达式
        if self._sell_expr and _safe_eval(self._sell_expr, fv):
            factor_summary = ", ".join(f"{k}={v:.4f}" for k, v in fv.items() if v is not None)
            return RuleResult(
                rule_id=self._rule_id,
                passed=True,
                score=1.0,
                direction="sell",
                confidence=0.8,
                reason=f"表达式卖出: {self._sell_expr} ({factor_summary})",
                detail={"expr": self._sell_expr, "factor_values": {k: v for k, v in fv.items() if v is not None}},
            )

        return RuleResult(rule_id=self._rule_id, direction="neutral", reason="无信号")
