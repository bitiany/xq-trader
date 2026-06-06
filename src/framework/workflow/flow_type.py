"""工作流核心类型定义。

参照 Dify 工作流设计，重构 State/Reducer/BaseNode：

1. 并行分支数据隔离：variables 使用 node_id 作为 key，避免并行分支写同名 key 互相覆盖
2. 新增 parallel_outputs：专门存储并行分支的输出，按 (fan_out_source, branch_node_id) 索引
3. 新增 interrupt_info：标准化人工确认节点的中断信息结构
4. merge_variables reducer：深度合并，并行分支结果各自独立存储
"""
from __future__ import annotations

import copy
import json
import re
from abc import ABC, abstractmethod
from enum import Enum
from typing import Annotated, Any

from typing_extensions import TypedDict

from framework.commons.logger import get_logger
from framework.commons.resolver.placeholder import PlaceholderResolver

logger = get_logger(__name__)

# 工作流全局共享的 PlaceholderResolver 实例
_resolver = PlaceholderResolver()

# flow JSON 中的 {var} 语法转换为 ${var} 语法的正则
_BRACE_TO_DOLLAR = re.compile(r'(?<!\$)\{(\w+)\}')


class ConditionType(str, Enum):
    NOT_NULL = "not-null"
    NULL = "null"
    EQUALS = "equals"
    NOT_EQUALS = "not-equals"
    GREATER_THAN = "greater-than"
    LESS_THAN = "less-than"
    CONTAINS = "contains"
    TRUE = "true"
    FALSE = "false"


def merge_variables(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """深度合并变量字典。

    规则：
    - 顶层 key 不冲突时直接合并
    - 顶层 key 冲突时，若两边都是 dict 则递归合并，否则 right 覆盖 left
    - 并行场景下，每个分支以 node_id 为 key 写入，天然不冲突
    """
    merged = copy.deepcopy(left)
    for key, value in right.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = merge_variables(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def keep_first(left: Any, right: Any) -> Any:
    """保留第一个非空值，用于单值字段（content, execute_id 等）。

    仅将 None 和空字符串视为"空"，0 是合法数值。
    """
    if left is not None and left != "":
        return left
    return right


class State(TypedDict, total=False):
    """工作流全局状态。

    variables: 节点输出变量，key 为 node_id，value 为该节点的输出
    context: 全局上下文（如输入参数）
    content: 最终输出内容
    execute_id: 工作流执行 ID
    workspace_id: 工作空间 ID
    parallel_outputs: 并行分支输出收集，key=f"{fan_out_source}::{branch_node_id}"
    interrupt_info: 人工确认中断信息（标准化结构）
    """
    variables: Annotated[dict[str, Any], merge_variables]
    context: Annotated[dict[str, Any], merge_variables]
    content: Annotated[str, keep_first]
    execute_id: Annotated[str, keep_first]
    workspace_id: Annotated[str, keep_first]
    parallel_outputs: Annotated[dict[str, Any], merge_variables]
    interrupt_info: Annotated[dict[str, Any], merge_variables]


class BaseNode(ABC):
    """工作流节点基类。

    所有节点类型（Start/End/Tool/Switch/HumanInput/SubGraph）均继承此类。
    提供统一的变量解析方法，所有子类共享同一个 PlaceholderResolver 实例。
    """

    def __init__(self, id: str, node_config: dict[str, Any]) -> None:
        self.id = id
        self.node_config = node_config

    @abstractmethod
    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        pass

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        return self.invoke(state)

    @staticmethod
    def _build_context(state: dict[str, Any]) -> dict[str, Any]:
        """构建变量解析上下文：context + variables 合并。"""
        return {**state.get("context", {}), **state.get("variables", {})}

    @staticmethod
    def _normalize_template(template: str) -> str:
        """将 flow JSON 中的 {var} 语法统一转换为 ${var} 语法。"""
        return _BRACE_TO_DOLLAR.sub(r'${\1}', template)

    def resolve_template(self, template: str, state: dict[str, Any], preserve_type: bool = True) -> Any:
        """使用共享 resolver 解析模板字符串。

        Args:
            template: 包含 {var} 或 ${var} 占位符的模板
            state: 工作流状态
            preserve_type: 是否保留原始类型
        """
        normalized = self._normalize_template(template)
        context = self._build_context(state)
        return _resolver.resolve(normalized, context=context, preserve_type=preserve_type)

    def extract_variables(self, state: dict[str, Any]) -> dict[str, Any]:
        """从 state 中解析节点配置的变量模板。"""
        props = self.node_config.get("props", {})
        variables: dict[str, Any] = {}
        if "variables" not in props:
            return variables
        for var in props["variables"]:
            var_name = var.get("variable")
            variable_type = var.get("type", "text")
            var_value_template = var.get("value", "")
            value = self.resolve_template(var_value_template, state, preserve_type=True)
            if variable_type == "json" and isinstance(value, str):
                value = json.loads(value)
            variables[var_name] = value
        return variables
