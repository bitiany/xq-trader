"""Start 节点 — 工作流入口，初始化变量映射。"""
from __future__ import annotations

from typing import Any

from framework.commons.logger import get_logger
from framework.workflow.flow_type import BaseNode

logger = get_logger(__name__)


class StartNode(BaseNode):

    def __init__(self, id: str, node_config: dict[str, Any]):
        super().__init__(id=id, node_config=node_config)

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        if "variables" not in state:
            state["variables"] = {}

        props = self.node_config.get("props", {})
        variables = props.get("variables", [])

        node_id = self.node_config.get("id")
        if node_id not in state["variables"]:
            state["variables"][node_id] = {}

        for var in variables:
            var_name = var.get("variable")
            if var_name in state["variables"]:
                state["variables"][node_id][var_name] = state["variables"][var_name]

        logger.debug(f"StartNode [{self.id}] done | vars: {len(variables)}")
        return state

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        return self.invoke(state)
