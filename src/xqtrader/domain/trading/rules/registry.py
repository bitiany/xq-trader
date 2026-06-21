"""规则注册表 — 管理表达式规则和 SPI 插件规则"""

from __future__ import annotations

from typing import Any

from framework.commons.logger import get_logger

from .base import RuleContext, RulePlugin, RuleResult
from .expression.evaluator import ExpressionEvaluator
from .expression.parser import ASTNode, parse_expression

logger = get_logger(__name__)


class ExpressionRule:
    """表达式规则 — 声明式规则，通过表达式字符串定义逻辑"""

    def __init__(
        self,
        rule_id: str,
        name: str,
        category: str,
        expression: str,
        signal_mapping: dict[str, Any] | None = None,
        default_config: dict[str, Any] | None = None,
    ) -> None:
        self.rule_id = rule_id
        self.name = name
        self.category = category
        self.expression = expression
        self.signal_mapping = signal_mapping or {}
        self.default_config = default_config or {}
        self._ast: ASTNode | None = None
        self._evaluator = ExpressionEvaluator()

    def get_ast(self) -> ASTNode:
        """获取表达式 AST（带缓存）"""
        if self._ast is None:
            self._ast = parse_expression(self.expression)
        return self._ast

    async def evaluate(self, context: RuleContext) -> RuleResult:
        """求值表达式规则"""
        try:
            ast = self.get_ast()
            result = self._evaluator.evaluate(
                ast=ast,
                factor_values=context.factor_values,
                factor_series=context.factor_series,
                cross_section_df=context.cross_section_df,
            )
        except (KeyError, ValueError) as e:
            logger.warning(f"表达式规则求值异常: rule={self.rule_id} error={e}")
            return RuleResult(rule_id=self.rule_id, passed=False, detail={"error": str(e)})

        # 截面模式：result 是 Series[bool] 或 Series[float]
        if hasattr(result, "__len__") and not isinstance(result, (str, bytes)):
            # 截面模式由 SelectionEngine 批量处理，此处不应走到
            return RuleResult(
                rule_id=self.rule_id,
                passed=bool(result),
                score=float(result) if not hasattr(result, "__iter__") else 0.0,
                detail={"expression": self.expression, "raw_result": "series"},
            )

        # 时序模式：result 是 bool 或 float
        passed = bool(result) if isinstance(result, (bool, int)) else True
        score = float(result) if isinstance(result, (int, float)) else (1.0 if passed else 0.0)

        # 信号映射
        direction = "neutral"
        confidence = score
        if self.signal_mapping:
            if passed and "true" in self.signal_mapping:
                mapping = self.signal_mapping["true"]
                direction = mapping.get("direction", "long")
                confidence = mapping.get("confidence", score)
            elif not passed and "false" in self.signal_mapping:
                mapping = self.signal_mapping["false"]
                direction = mapping.get("direction", "neutral")
                confidence = mapping.get("confidence", 0.0)

        return RuleResult(
            rule_id=self.rule_id,
            passed=passed,
            score=score,
            direction=direction,
            confidence=confidence,
            detail={"expression": self.expression, "raw_result": result},
        )


class RuleRegistry:
    """规则注册表 — 统一管理表达式规则和 SPI 插件规则"""

    def __init__(self) -> None:
        self._expression_rules: dict[str, ExpressionRule] = {}
        self._spi_plugins: dict[str, RulePlugin] = {}

    def register_expression(
        self,
        rule_id: str,
        name: str,
        category: str,
        expression: str,
        signal_mapping: dict[str, Any] | None = None,
        default_config: dict[str, Any] | None = None,
    ) -> None:
        """注册表达式规则"""
        self._expression_rules[rule_id] = ExpressionRule(
            rule_id=rule_id,
            name=name,
            category=category,
            expression=expression,
            signal_mapping=signal_mapping,
            default_config=default_config,
        )
        logger.debug(f"注册表达式规则: {rule_id}")

    def register_plugin(self, plugin: RulePlugin) -> None:
        """注册 SPI 插件规则"""
        self._spi_plugins[plugin.rule_id] = plugin
        logger.debug(f"注册 SPI 插件: {plugin.rule_id}")

    def get(self, rule_id: str) -> ExpressionRule | RulePlugin:
        """获取规则实例"""
        if rule_id in self._spi_plugins:
            return self._spi_plugins[rule_id]
        if rule_id in self._expression_rules:
            return self._expression_rules[rule_id]
        msg = f"规则不存在: {rule_id}"
        raise KeyError(msg)

    def has(self, rule_id: str) -> bool:
        """检查规则是否存在"""
        return rule_id in self._expression_rules or rule_id in self._spi_plugins

    def list_rules(self) -> list[dict[str, Any]]:
        """列出所有已注册规则"""
        rules: list[dict[str, Any]] = []
        for rule_id, rule in self._expression_rules.items():
            rules.append({
                "rule_id": rule_id,
                "name": rule.name,
                "category": rule.category,
                "type": "expression",
                "expression": rule.expression,
            })
        for rule_id, plugin in self._spi_plugins.items():
            rules.append({
                "rule_id": rule_id,
                "name": plugin.name,
                "category": plugin.category,
                "type": "spi",
                "factor_ids": plugin.factor_ids,
            })
        return rules

    @property
    def expression_rules(self) -> dict[str, ExpressionRule]:
        return self._expression_rules

    @property
    def spi_plugins(self) -> dict[str, RulePlugin]:
        return self._spi_plugins
