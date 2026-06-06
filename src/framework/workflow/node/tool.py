"""Tool 节点 — 执行外部工具，结果以 node_id 为 key 写入 variables。

并行分支数据隔离：结果写入 state["variables"][self.id]，
多个并行分支即使使用同一个 tool，各自的结果也不会互相覆盖。
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool

from framework.commons.logger import get_logger
from framework.workflow.flow_type import BaseNode

logger = get_logger(__name__)


class ToolNode(BaseNode):

    def __init__(self, id: str, node_config: dict[str, Any]):
        super().__init__(id=id, node_config=node_config)
        self.tools: dict[str, BaseTool] = {}

    def bind(self, name: str, tool: BaseTool) -> None:
        self.tools[name] = tool

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        props = self.node_config.get("props", {})
        variables = self.extract_variables(state)
        tool_name = props.get("name", self.id)
        tool = self.tools[tool_name]
        result = tool.invoke(variables)

        # 以 node_id 为 key 存储，保证并行安全
        state["variables"][self.id] = result

        logger.debug(
            f"ToolNode [{self.id}] done | tool: {tool_name} | result type: {type(result).__name__}"
        )
        return state

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        from langgraph.errors import GraphInterrupt

        props = self.node_config.get("props", {})
        variables = self.extract_variables(state)
        tool_name = props.get("name", self.id)

        logger.info(
            f"ToolNode [{self.id}] starting | tool: {tool_name} | vars: {list(variables.keys())}"
        )

        tool = self.tools[tool_name]
        try:
            result = await tool.ainvoke(input=variables)
        except GraphInterrupt:
            raise
        except Exception as e:
            logger.error(f"ToolNode [{self.id}] tool error: {e}", exc_info=True)
            raise

        # 以 node_id 为 key 存储，保证并行安全
        state["variables"][self.id] = result

        logger.info(
            f"ToolNode [{self.id}] done | tool: {tool_name} | result type: {type(result).__name__}"
        )
        return state
