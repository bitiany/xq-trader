"""表达式规则插件 — 内置默认插件

通过 buy_expr / sell_expr 定义信号条件，支持因子名作为变量名。
表达式语法参考 QLib:
  - 比较运算: rsi < 30, hist > 0, macd > signal
  - 逻辑运算: rsi < 30 and hist > 0
  - 算术运算: close / open > 1.05
  - 函数: abs(hist) > 0.1, max(rsi_6, rsi_14) > 70
"""

import ast
import logging
import math

from ..core import RuleConfig, RuleContext, RuleResult, RulePlugin

logger = logging.getLogger(__name__)

# 安全的表达式求值环境
_SAFE_FUNCS = {
    "abs": abs,
    "max": max,
    "min": min,
    "round": round,
    "int": int,
    "float": float,
    "bool": bool,
    "math": math,
    "nan": float("nan"),
    "inf": float("inf"),
}

# 允许的 AST 节点类型（白名单）
_ALLOWED_AST_NODES = (
    ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare,
    ast.Name, ast.Constant, ast.And, ast.Or, ast.Not,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
    ast.Lt, ast.Gt, ast.LtE, ast.GtE, ast.Eq, ast.NotEq,
    ast.USub, ast.UAdd, ast.Load,
)


class _SafeExprValidator(ast.NodeVisitor):
    """验证表达式 AST 是否只包含安全节点，阻止代码注入"""

    def visit_Call(self, node: ast.Call):
        """仅允许调用 _SAFE_FUNCS 中的函数"""
        if not isinstance(node.func, ast.Name) or node.func.id not in _SAFE_FUNCS:
            raise ValueError(f"不允许的函数调用: {ast.dump(node.func, include_attributes=False)}")
        self.generic_visit(node)

    def generic_visit(self, node: ast.AST):
        if not isinstance(node, _ALLOWED_AST_NODES):
            raise ValueError(f"不允许的表达式节点: {type(node).__name__}")
        super().generic_visit(node)


def _safe_eval(expr: str, namespace: dict[str, float]) -> bool:
    """安全地求值表达式，通过 AST 白名单阻止代码注入"""
    try:
        tree = ast.parse(expr, mode="eval")
        _SafeExprValidator().visit(tree)
        full_ns = {**_SAFE_FUNCS, **namespace}
        return bool(eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, full_ns))
    except Exception as e:
        logger.warning(f"表达式求值失败: expr='{expr}', error={e}")
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
