"""SubGraph 节点 — 嵌套子工作流。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from framework.commons.exceptions import WorkflowConfigError
from framework.commons.logger import get_logger
from framework.workflow.flow_type import BaseNode

if TYPE_CHECKING:
    from framework.workflow.compiler import FlowCompiler

logger = get_logger(__name__)


class SubGraphNode(BaseNode):

    def __init__(self, id: str, node_config: dict[str, Any]):
        super().__init__(id=id, node_config=node_config)
        props = node_config.get("props", {})
        self.workflow_id = props.get("workflow_id")
        self.input_mapping: dict[str, str] = props.get("input_mapping", {})
        self.output_mapping: dict[str, str] = props.get("output_mapping", {})
        self._compiler: FlowCompiler | None = None

        if not self.workflow_id:
            raise WorkflowConfigError(
                f"SubGraphNode '{id}' requires 'workflow_id' in props"
            )

    def _ensure_compiler(self) -> FlowCompiler:
        """延迟加载子工作流编译器，使用统一的 load_subgraph 入口。"""
        if self._compiler is None:
            from framework.workflow.compiler import load_subgraph
            self._compiler = load_subgraph(self.workflow_id)
        return self._compiler

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        compiler = self._ensure_compiler()

        child_variables: dict[str, Any] = {}

        logger.info(
            f"SubGraph:{self.workflow_id} input projection | mappings: {len(self.input_mapping)}"
        )
        for target_key, source_template in self.input_mapping.items():
            value = self.resolve_template(source_template, state)
            child_variables[target_key] = value
            logger.debug(
                f"   map: {source_template} -> {target_key} = {str(value)[:80]}"
            )

        child_state: dict[str, Any] = {
            "variables": child_variables,
            "context": {},
            "content": "",
            "execute_id": state.get("execute_id", ""),
            "workspace_id": state.get("workspace_id", ""),
            "parallel_outputs": {},
            "interrupt_info": {},
        }

        child_config: dict[str, Any] = {
            "execute_id": state.get("execute_id", ""),
            "parent_flow_id": self.workflow_id,
        }

        logger.info(f"SubGraph:{self.workflow_id} executing")
        from framework.workflow.engine import FlowEngine
        engine = FlowEngine.from_compiler(compiler)
        result_state = await engine.ainvoke(child_state, child_config)
        logger.info(f"SubGraph:{self.workflow_id} done")

        result_data = result_state.get("variables", {})
        parent_updates: dict[str, Any] = {}

        logger.info(
            f"SubGraph:{self.workflow_id} output projection | mappings: {len(self.output_mapping)}"
        )
        for target_key, source_template in self.output_mapping.items():
            normalized = self._normalize_template(source_template)
            from framework.workflow.flow_type import _resolver
            value = _resolver.resolve(normalized, context=result_data, preserve_type=True)
            parent_updates[target_key] = value
            logger.debug(
                f"   map: {source_template} -> {target_key} = {str(value)[:80]}"
            )

        state["variables"].update(parent_updates)
        return state

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("SubGraphNode 仅支持异步执行")
