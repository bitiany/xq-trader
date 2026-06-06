"""Switch 节点 — 条件分支路由。

使用策略模式将每种条件类型的判断逻辑封装为独立的评估器，
通过 ConditionType 枚举注册到 dispatch 表，新增条件类型只需添加评估器子类。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from jsonpath_ng import parse  # type: ignore[import-untyped]

from framework.commons.exceptions import WorkflowConditionError
from framework.commons.logger import get_logger
from framework.workflow.flow_type import BaseNode, ConditionType

logger = get_logger(__name__)


# ==================== 条件评估器策略模式 ====================

class ConditionEvaluator(ABC):
    """条件评估器基类。"""

    @abstractmethod
    def evaluate(self, value: Any, target: Any | None) -> bool:
        """评估条件是否满足。

        Args:
            value: 从 state 中提取的变量值
            target: 条件配置中的目标值（部分条件类型不需要）

        Returns:
            条件是否满足
        """


class NotNullEvaluator(ConditionEvaluator):
    def evaluate(self, value: Any, target: Any | None) -> bool:
        if value is None:
            return False
        if isinstance(value, str) and value.strip() == "":
            return False
        return True


class NullEvaluator(ConditionEvaluator):
    def evaluate(self, value: Any, target: Any | None) -> bool:
        if value is None:
            return True
        if isinstance(value, str) and str(value).strip() == "":
            return True
        return False


class EqualsEvaluator(ConditionEvaluator):
    def evaluate(self, value: Any, target: Any | None) -> bool:
        return value is not None and target is not None and value == target


class NotEqualsEvaluator(ConditionEvaluator):
    def evaluate(self, value: Any, target: Any | None) -> bool:
        if value is None and target is None:
            return False
        return bool(value != target)


class GreaterThanEvaluator(ConditionEvaluator):
    def evaluate(self, value: Any, target: Any | None) -> bool:
        return value is not None and target is not None and value > target


class LessThanEvaluator(ConditionEvaluator):
    def evaluate(self, value: Any, target: Any | None) -> bool:
        return value is not None and target is not None and value < target


class ContainsEvaluator(ConditionEvaluator):
    def evaluate(self, value: Any, target: Any | None) -> bool:
        return (
            isinstance(value, str)
            and isinstance(target, str)
            and target in value
        )


class TrueEvaluator(ConditionEvaluator):
    def evaluate(self, value: Any, target: Any | None) -> bool:
        if isinstance(value, bool) and value is True:
            return True
        if isinstance(value, str) and value.lower() in ("true", "1", "yes", "on"):
            return True
        return False


class FalseEvaluator(ConditionEvaluator):
    def evaluate(self, value: Any, target: Any | None) -> bool:
        if isinstance(value, bool) and value is False:
            return True
        if isinstance(value, str) and value.lower() in ("false", "0", "no", "off"):
            return True
        return False


# 条件类型 → 评估器实例的注册表
EVALUATOR_REGISTRY: dict[ConditionType, ConditionEvaluator] = {
    ConditionType.NOT_NULL: NotNullEvaluator(),
    ConditionType.NULL: NullEvaluator(),
    ConditionType.EQUALS: EqualsEvaluator(),
    ConditionType.NOT_EQUALS: NotEqualsEvaluator(),
    ConditionType.GREATER_THAN: GreaterThanEvaluator(),
    ConditionType.LESS_THAN: LessThanEvaluator(),
    ConditionType.CONTAINS: ContainsEvaluator(),
    ConditionType.TRUE: TrueEvaluator(),
    ConditionType.FALSE: FalseEvaluator(),
}


# ==================== SwitchNode ====================

def _convert_template_to_jsonpath(template_str: str) -> tuple[str, bool]:
    if not isinstance(template_str, str):
        return template_str, False
    import re
    pattern = r"\{([^}]+)\}"
    converted = re.sub(pattern, r"$..\1", template_str)
    return converted, converted != template_str


class SwitchNode(BaseNode):

    def __init__(self, id: str, node_config: dict[str, Any]):
        super().__init__(id=id, node_config=node_config)

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        logger.debug(f"SwitchNode [{self.node_config.get('id')}] starting")
        props = self.node_config.get("props", {})
        cases = props.get("case", [])
        search_data = {**state.get("context", {}), **state.get("variables", {})}
        matched_case = None

        for case in cases:
            condition = case.get("condition", {})
            case_type_str = condition.get("type")
            value = self._extract_value(condition.get("variable"), search_data)
            target = (
                self._extract_value(condition.get("value"), search_data)
                if "value" in condition
                else None
            )

            try:
                case_type = ConditionType(case_type_str)
            except ValueError:
                logger.warning(f"Unknown condition type: {case_type_str}")
                continue

            evaluator = EVALUATOR_REGISTRY.get(case_type)
            if evaluator is None:
                logger.warning(f"No evaluator for condition type: {case_type_str}")
                continue

            if evaluator.evaluate(value, target):
                matched_case = case.get("id")
                break

        if matched_case:
            state["variables"][self.id] = matched_case
            logger.info(
                f"SwitchNode [{self.node_config.get('id')}] matched | branch: {matched_case}"
            )
        else:
            raise WorkflowConditionError(
                self.node_config.get('id', self.id),
                [c.get("id") for c in cases]
            )

        return state

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        return self.invoke(state)

    @classmethod
    def _extract_value(
        cls, variable: str | None, state: dict[str, Any]
    ) -> Any | None:
        if variable is None:
            return None
        jsonpath_expr_str, is_json_path = _convert_template_to_jsonpath(variable)
        if not is_json_path:
            return variable
        try:
            jsonpath_expr = parse(jsonpath_expr_str)
            matches = [match.value for match in jsonpath_expr.find(state)]
            return matches[0] if matches else None
        except Exception as e:
            raise WorkflowConditionError(
                "unknown",
                [f"Failed to extract value with JSONPath '{variable}': {e}"]
            ) from e
