"""表达式引擎 — AST 求值器"""

from __future__ import annotations

from typing import Any

import pandas as pd

from framework.commons.logger import get_logger

from .operators import OPERATOR_REGISTRY
from .parser import (
    ASTNode,
    CompareNode,
    FuncCallNode,
    IdentifierNode,
    LogicalNode,
    NumberNode,
)

logger = get_logger(__name__)

# 比较运算符
_CMP_OPS: dict[str, Any] = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


class ExpressionEvaluator:
    """表达式求值器 — 接收 AST + 数据上下文，返回求值结果

    支持两种求值模式：
    1. 截面模式：传入 cross_section_df (DataFrame, index=symbol)，对整列操作
    2. 时序模式：传入 factor_values (dict) + factor_series (dict)，对单标的操作
    """

    def evaluate(
        self,
        ast: ASTNode,
        factor_values: dict[str, float] | None = None,
        factor_series: dict[str, pd.Series] | None = None,
        cross_section_df: pd.DataFrame | None = None,
    ) -> Any:
        """求值入口

        Args:
            ast: 语法分析产出的 AST
            factor_values: 单标的因子值 {factor_id: value}
            factor_series: 因子历史序列 {factor_id: Series}
            cross_section_df: 截面数据 DataFrame(index=symbol, columns=factor_ids)

        Returns:
            截面模式: pd.Series(index=symbol)
            时序模式: bool | float
        """
        factor_values = factor_values or {}
        factor_series = factor_series or {}
        return self._eval_node(ast, factor_values, factor_series, cross_section_df)

    def _eval_node(
        self,
        node: ASTNode,
        factor_values: dict[str, float],
        factor_series: dict[str, pd.Series],
        cross_section_df: pd.DataFrame | None,
    ) -> Any:
        if isinstance(node, NumberNode):
            return node.value

        if isinstance(node, IdentifierNode):
            return self._resolve_identifier(node.name, factor_values, cross_section_df)

        if isinstance(node, CompareNode):
            left = self._eval_node(node.left, factor_values, factor_series, cross_section_df)  # type: ignore[arg-type]
            right = self._eval_node(node.right, factor_values, factor_series, cross_section_df)  # type: ignore[arg-type]
            return self._compare(left, right, node.op)

        if isinstance(node, LogicalNode):
            left = self._eval_node(node.left, factor_values, factor_series, cross_section_df)  # type: ignore[arg-type]
            right = self._eval_node(node.right, factor_values, factor_series, cross_section_df)  # type: ignore[arg-type]
            return self._logical(left, right, node.op)

        if isinstance(node, FuncCallNode):
            return self._call_func(node, factor_values, factor_series, cross_section_df)

        msg = f"未知 AST 节点类型: {type(node)}"
        raise ValueError(msg)

    def _resolve_identifier(
        self,
        name: str,
        factor_values: dict[str, float],
        cross_section_df: pd.DataFrame | None,
    ) -> Any:
        # 截面模式：从 DataFrame 列取值
        if cross_section_df is not None and name in cross_section_df.columns:
            return cross_section_df[name]
        # 时序模式：从因子值字典取值
        if name in factor_values:
            return factor_values[name]
        msg = f"未知标识符: '{name}'"
        raise KeyError(msg)

    def _compare(self, left: Any, right: Any, op: str) -> Any:
        cmp_fn = _CMP_OPS.get(op)
        if cmp_fn is None:
            msg = f"未知比较运算符: '{op}'"
            raise ValueError(msg)
        # 截面模式：Series op scalar → Series[bool]
        if isinstance(left, pd.Series) and isinstance(right, (int, float)):
            return cmp_fn(left, right)
        if isinstance(right, pd.Series) and isinstance(left, (int, float)):
            return cmp_fn(left, right)
        # 两个 Series
        if isinstance(left, pd.Series) and isinstance(right, pd.Series):
            return cmp_fn(left, right)
        # 标量
        return cmp_fn(left, right)

    def _logical(self, left: Any, right: Any, op: str) -> Any:
        if op == "and":
            if isinstance(left, pd.Series) and isinstance(right, pd.Series):
                return left & right
            if isinstance(left, pd.Series):
                return left if left.all() else pd.Series(False, index=left.index)
            if isinstance(right, pd.Series):
                return right if right.all() else pd.Series(False, index=right.index)
            return left and right
        if op == "or":
            if isinstance(left, pd.Series) and isinstance(right, pd.Series):
                return left | right
            if isinstance(left, pd.Series):
                return pd.Series(True, index=left.index) if left.any() else right
            if isinstance(right, pd.Series):
                return pd.Series(True, index=right.index) if right.any() else left
            return left or right
        msg = f"未知逻辑运算符: '{op}'"
        raise ValueError(msg)

    def _call_func(
        self,
        node: FuncCallNode,
        factor_values: dict[str, float],
        factor_series: dict[str, pd.Series],
        cross_section_df: pd.DataFrame | None,
    ) -> Any:
        func_name = node.name
        entry = OPERATOR_REGISTRY.get(func_name)
        if entry is None:
            msg = f"未知算子: '{func_name}'"
            raise ValueError(msg)

        func, is_cross_section, min_args, max_args = entry
        n_args = len(node.args)
        if n_args < min_args or n_args > max_args:
            msg = f"算子 '{func_name}' 参数数量错误: 期望 {min_args}-{max_args}, 实际 {n_args}"
            raise ValueError(msg)

        # 求值参数
        args = [
            self._eval_node(arg, factor_values, factor_series, cross_section_df)
            for arg in node.args
        ]

        # 截面算子：参数是 Series（整列），直接调用
        if is_cross_section:
            return func(*args)

        # 时序算子：参数可能是标量或 Series
        # 对于需要历史序列的算子（delta/ma/std/pct_change），从 factor_series 取
        if func_name in ("delta", "ma", "std", "pct_change"):
            series_args = self._resolve_series_args(node, factor_series, args)
            return func(*series_args)

        # 交叉算子：需要两个 Series
        if func_name in ("cross_above", "cross_below"):
            series_args = self._resolve_series_args(node, factor_series, args)
            return func(*series_args)

        # 通用算子：直接调用
        return func(*args)

    def _resolve_series_args(
        self,
        node: FuncCallNode,
        factor_series: dict[str, pd.Series],
        evaluated_args: list[Any],
    ) -> list[Any]:
        """将标识符参数替换为历史序列（如果可用）"""
        resolved: list[Any] = []
        for i, (arg_node, arg_val) in enumerate(zip(node.args, evaluated_args)):
            if isinstance(arg_node, IdentifierNode) and arg_node.name in factor_series:
                resolved.append(factor_series[arg_node.name])
            elif isinstance(arg_node, NumberNode) and i > 0:
                resolved.append(int(arg_val))
            else:
                resolved.append(arg_val)
        return resolved
