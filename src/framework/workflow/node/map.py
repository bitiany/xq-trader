"""Map 节点 — 对运行时列表动态并行执行同一个 worker 工具。"""
from __future__ import annotations

import asyncio
from typing import Any

from framework.commons.exceptions import WorkflowConfigError
from framework.commons.logger import get_logger
from framework.workflow.flow_type import BaseNode

logger = get_logger(__name__)


class MapNode(BaseNode):
    def __init__(self, id: str, node_config: dict[str, Any]):
        super().__init__(id=id, node_config=node_config)
        self.tools: dict[str, Any] = {}

    def bind(self, name: str, tool: Any) -> None:
        self.tools[name] = tool

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        raise WorkflowConfigError("MapNode only supports async execution")

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        props = self.node_config.get("props", {})
        items_template = props.get("items", "")
        item_variable = props.get("item_variable", "item")
        tool_name = props.get("name", self.id)
        concurrency = int(props.get("concurrency", 8))

        items = self.resolve_template(items_template, state, preserve_type=True)
        if not isinstance(items, list):
            raise WorkflowConfigError(f"MapNode [{self.id}] items must resolve to list")

        if tool_name not in self.tools:
            raise WorkflowConfigError(f"MapNode [{self.id}] tool not bound: {tool_name}")

        variables = self.extract_variables(state)
        tool = self.tools[tool_name]
        semaphore = asyncio.Semaphore(concurrency)

        async def run_one(item: Any) -> Any:
            async with semaphore:
                worker_input = {**variables, item_variable: item}
                return await tool.ainvoke(input=worker_input)

        results = await asyncio.gather(*(run_one(item) for item in items))
        state["variables"][self.id] = {
            "items": results,
            "total": len(results),
        }
        logger.info("MapNode [%s] done | items: %d", self.id, len(results))
        return state
