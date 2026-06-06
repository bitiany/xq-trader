"""End 节点 — 工作流出口，提取最终输出。"""
from __future__ import annotations

from typing import Any

from framework.commons.logger import get_logger
from framework.workflow.flow_type import BaseNode

logger = get_logger(__name__)


class EndNode(BaseNode):

    def __init__(self, id: str, node_config: dict[str, Any]):
        super().__init__(id=id, node_config=node_config)

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        props = self.node_config.get("props", {})
        output_template = props.get("output")

        if output_template:
            output_value = self.resolve_template(output_template, state)
            state["content"] = str(output_value) if output_value is not None else ""
            logger.info(
                f"EndNode [{self.id}] output extracted | len: {len(state['content'])}"
            )

        return state

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        return self.invoke(state)
