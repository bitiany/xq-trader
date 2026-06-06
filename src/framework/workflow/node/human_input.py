"""HumanInput 节点 — 人工确认/审批节点（参照 Dify Human Input 设计）。

设计要点：
1. 声明式配置：在 flow JSON 中声明式定义表单内容、用户动作、超时策略
2. 标准化 interrupt 数据结构：前端可统一渲染
3. 动作路由：用户选择不同动作后，工作流走不同分支
4. 超时策略：支持自动超时处理

flow JSON 配置示例：
{
    "id": "review",
    "type": "human_input",
    "name": "人工审阅",
    "props": {
        "form": {
            "title": "请审阅板块轮动结果",
            "description": "基于轮动分析，请选择要操作的板块",
            "fields": [
                {"name": "selected_sectors", "type": "select", "label": "选择板块",
                 "options_source": "${single_rotation.top_sectors}", "multiple": true},
                {"name": "comment", "type": "text", "label": "备注", "required": false}
            ]
        },
        "actions": [
            {"id": "approve", "label": "确认", "style": "primary"},
            {"id": "reject", "label": "拒绝", "style": "danger"},
            {"id": "retry", "label": "重试", "style": "default"}
        ],
        "timeout": {
            "seconds": 3600,
            "default_action": "reject"
        }
    }
}
"""
from __future__ import annotations

import time
from typing import Any

from framework.commons.exceptions import WorkflowResumeError
from framework.commons.logger import get_logger
from framework.workflow.flow_type import BaseNode

logger = get_logger(__name__)


class HumanInputNode(BaseNode):
    """人工确认节点。

    执行流程：
    1. 从 state 中收集表单数据（动态解析 fields 中的变量引用）
    2. 调用 langgraph.interrupt() 暂停工作流
    3. 用户通过 resume API 提交选择后，工作流恢复
    4. 将用户选择写入 state["variables"][self.id]
    5. 将用户动作写入 state["variables"][f"{self.id}__action"]，供 Switch 节点路由
    """

    def __init__(self, id: str, node_config: dict[str, Any]):
        super().__init__(id=id, node_config=node_config)
        props = node_config.get("props", {})
        self.form_config: dict[str, Any] = props.get("form", {})
        self.actions: list[dict[str, Any]] = props.get("actions", [])
        self.timeout_config: dict[str, Any] = props.get("timeout", {})

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("HumanInputNode 仅支持异步执行")

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        from langgraph.types import interrupt

        # 构建标准化 interrupt 数据
        interrupt_data = self._build_interrupt_data(state)

        logger.info(
            f"HumanInputNode [{self.id}] interrupting | "
            f"title: {interrupt_data.get('title', '')} | "
            f"actions: {[a['id'] for a in interrupt_data.get('actions', [])]}"
        )

        # 写入 interrupt_info 供 API 层读取
        state["interrupt_info"] = {
            "node_id": self.id,
            "node_type": "human_input",
            "title": interrupt_data.get("title", ""),
            "actions": [a["id"] for a in self.actions],
            "timeout_seconds": self.timeout_config.get("seconds", 0),
        }

        # 调用 interrupt 暂停工作流
        user_response = interrupt(interrupt_data)

        # 处理用户响应
        self._process_response(state, user_response)

        return state

    def _build_interrupt_data(self, state: dict[str, Any]) -> dict[str, Any]:
        """构建标准化的 interrupt 数据结构。"""
        from framework.commons.resolver.placeholder import PlaceholderResolver
        resolver = PlaceholderResolver()
        context = {**state.get("context", {}), **state.get("variables", {})}

        # 解析表单字段中的动态数据
        resolved_fields: list[dict[str, Any]] = []
        for field in self.form_config.get("fields", []):
            resolved_field: dict[str, Any] = {
                "name": field.get("name"),
                "type": field.get("type", "text"),
                "label": field.get("label", ""),
                "required": field.get("required", True),
                "multiple": field.get("multiple", False),
            }
            # 解析 options_source 中的变量引用
            options_source = field.get("options_source")
            if options_source:
                resolved_options = resolver.resolve(
                    options_source, context=context, preserve_type=True
                )
                if resolved_options is not None:
                    resolved_field["options"] = resolved_options
            # 解析 default_value 中的变量引用
            default_value = field.get("default_value")
            if default_value:
                resolved_default = resolver.resolve(
                    default_value, context=context, preserve_type=True
                )
                if resolved_default is not None:
                    resolved_field["default_value"] = resolved_default
            resolved_fields.append(resolved_field)

        return {
            "node_id": self.id,
            "node_type": "human_input",
            "title": self.form_config.get("title", ""),
            "description": self.form_config.get("description", ""),
            "fields": resolved_fields,
            "actions": self.actions,
            "timeout_seconds": self.timeout_config.get("seconds", 0),
            "timestamp": time.time(),
        }

    def _process_response(
        self, state: dict[str, Any], user_response: Any
    ) -> None:
        """处理用户 resume 提交的响应。"""
        if isinstance(user_response, dict):
            action = user_response.get("action", "approve")
            form_data = user_response.get("form_data", {})
        else:
            raise WorkflowResumeError(
                f"HumanInputNode [{self.id}] resume_value must be a dict with 'action' and 'form_data', "
                f"got {type(user_response).__name__}: {user_response}"
            )

        # 将用户选择写入 variables
        state["variables"][self.id] = form_data
        # 将用户动作写入 variables，供下游 Switch 节点路由
        state["variables"][f"{self.id}__action"] = action

        logger.info(
            f"HumanInputNode [{self.id}] resumed | action: {action} | "
            f"form_data keys: {list(form_data.keys()) if isinstance(form_data, dict) else 'scalar'}"
        )
