"""工作流图编译器 — 从 flow JSON 配置构建 LangGraph StateGraph。

职责单一：只负责将 JSON 配置编译为可执行的 CompiledStateGraph，
不涉及运行时执行逻辑。
"""
from __future__ import annotations

import importlib
import json
import os
import uuid
from collections.abc import Callable
from typing import Any

from langchain_core.tools.structured import StructuredTool
from langgraph.graph import END, StateGraph
from langgraph.types import Send

from framework.commons.exceptions import (
    WorkflowConfigError,
    WorkflowNodeError,
    WorkflowToolLoadError,
)
from framework.commons.logger import get_logger
from framework.config.settings import settings
from framework.workflow.flow_type import BaseNode, State
from framework.workflow.node import NODE_TYPE_CLASSES_MAPPING, NodeType

logger = get_logger(__name__)


def create_tool_instance(name: str, class_path: str) -> Any:
    """动态加载工具类实例。"""
    if not class_path:
        raise WorkflowConfigError(
            f"Tool '{name}' missing 'class' config. "
            f"Add 'class' field, e.g.: \"class\": \"module.path.ClassName\""
        )
    try:
        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        tool_class = getattr(module, class_name)
        if isinstance(tool_class, StructuredTool):
            return tool_class
        return tool_class()
    except (ImportError, AttributeError) as e:
        logger.error(f"Cannot load tool '{name}' from '{class_path}': {e}", exc_info=True)
        raise WorkflowToolLoadError(f"Cannot load tool '{name}' from '{class_path}': {e}") from e


class FlowCompiler:
    """工作流图编译器。

    负责将 flow JSON 配置编译为 LangGraph CompiledStateGraph。
    编译产物包含编译后的图、节点配置、节点执行器等，
    供 FlowEngine 在运行时使用。
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.flow_id: str = config.get("id", str(uuid.uuid4())[:8])
        self.node_configs: dict[str, dict[str, Any]] = {}
        self.executors: dict[str, BaseNode] = {}
        self.sub_processes: list[FlowCompiler] = []
        self._input_schema: dict[str, str] | None = config.get("input_schema")
        self._output_schema: dict[str, str] | None = config.get("output_schema")
        self._original_config = config

    @property
    def total_nodes(self) -> int:
        """计算工作流节点总数（含子工作流）。"""
        sub_total = sum(sub.total_nodes for sub in self.sub_processes)
        return (
            len([k for k in self.compiled_graph.nodes.keys() if k != "__start__"])
            + sub_total
        )

    def compile(self, checkpointer: Any | None = None) -> None:
        """编译工作流配置为 LangGraph 图。

        Args:
            checkpointer: checkpoint 持久化存储。未提供时自动获取 PostgresSaver。
        """
        graph = StateGraph(State)

        nodes = self._original_config.get("graph", {}).get("nodes", [])
        for node in nodes:
            node_id = node.get("id")
            self.node_configs[node_id] = node
            self._add_node(graph, node, node_id)

        edges = self._original_config.get("graph", {}).get("edges", [])

        edges_by_from: dict[str, list[dict[str, Any]]] = {}
        for edge in edges:
            from_node = edge["from"]
            edges_by_from.setdefault(from_node, []).append(edge)

        for from_node, node_edges in edges_by_from.items():
            from_node_config = self.node_configs.get(from_node, {})
            edge_type = node_edges[0].get("type", "normal")

            if from_node_config.get("type") == "switch":
                self._add_conditional_edge(graph, from_node, node_edges)
            elif edge_type == "parallel" or len(node_edges) > 1:
                self._add_parallel_edge(graph, from_node, node_edges)
            else:
                graph.add_edge(from_node, node_edges[0]["to"])

        graph.set_entry_point(nodes[0]["id"])
        graph.set_finish_point("end")

        if checkpointer is None:
            from framework.workflow.checkpoint_registry import get_checkpointer
            checkpointer = get_checkpointer(self.flow_id)

        self.compiled_graph = graph.compile(checkpointer=checkpointer)

        logger.info(
            f"FlowCompiler [{self.flow_id}] compiled | "
            f"nodes: {len(self.node_configs)}"
        )

    def _add_node(
        self, graph: StateGraph, node: dict[str, Any], node_id: str
    ) -> None:
        """添加节点到图中。"""
        node_type = node.get("type")

        if node_type == "subgraph":
            sub_workflow_id = node.get("props", {}).get("workflow_id")
            if sub_workflow_id:
                logger.info(f"SubGraph integrating: {sub_workflow_id}")
                sub_compiler = load_subgraph(sub_workflow_id)
                graph.add_node(node_id, sub_compiler.compiled_graph)
                self.node_configs[node_id] = node
                self.sub_processes.append(sub_compiler)
                return

        node_func = self._create_node_func(node, node_id)
        graph.add_node(node_id, node_func)

    def _create_node_func(
        self, n_config: dict[str, Any], nid: str
    ) -> Callable[..., Any]:
        """创建节点执行函数。"""
        n_type = n_config.get("type")
        self.executors[nid] = self._load_node_by_config(n_config)

        async def async_node_wrapper(state: dict[str, Any]) -> dict[str, Any]:
            # 检查工作流是否已被停止
            execute_id = state.get("execute_id", "")
            if execute_id:
                await self._check_stopped(execute_id)

            executor = self.executors.get(nid)
            if executor is None:
                raise WorkflowNodeError(nid, str(n_type or ""), "No executor found")
            try:
                logger.debug(
                    f"FlowEngine [{self.flow_id}] node [{nid}] ({n_type}) executing"
                )
                node_state = await executor.ainvoke(state)
                logger.debug(
                    f"FlowEngine [{self.flow_id}] node [{nid}] ({n_type}) done"
                )
                return node_state
            except BaseException as e:
                from langgraph.errors import GraphInterrupt
                if isinstance(e, GraphInterrupt):
                    logger.info(
                        f"FlowEngine [{self.flow_id}] node [{nid}] interrupted (HumanInput)"
                    )
                    raise
                logger.error(
                    f"FlowEngine [{self.flow_id}] node [{nid}] ({n_type}) failed: {e}",
                    exc_info=True,
                )
                raise

        return async_node_wrapper

    @staticmethod
    async def _check_stopped(execute_id: str) -> None:
        """检查工作流是否已被停止，若已停止则抛出异常终止执行。"""
        from framework.workflow.models import WorkflowRun
        run = await WorkflowRun.get_one_or_none(run_id=execute_id)
        if run is not None and run.status == "stopped":
            raise WorkflowNodeError("workflow", "system", "Workflow has been stopped by user")

    @classmethod
    def _add_conditional_edge(
        cls,
        graph: StateGraph,
        from_node: str,
        node_edges: list[dict[str, Any]],
    ) -> None:
        """添加条件边（Switch 节点）。"""
        def make_conditional_edge(
            edges_list: list[dict[str, Any]], condition_node_id: str
        ) -> Callable[[dict[str, Any]], str]:
            def conditional_edge(state: dict[str, Any]) -> str:
                if "variables" in state and condition_node_id in state["variables"]:
                    case_id = state["variables"][condition_node_id]
                    next_edge = next(
                        (e for e in edges_list if e.get("condition") == case_id),
                        None,
                    )
                    if next_edge:
                        return str(next_edge["to"])
                return str(END)

            return conditional_edge

        graph.add_conditional_edges(
            from_node, make_conditional_edge(node_edges, from_node)
        )

    @classmethod
    def _add_parallel_edge(
        cls,
        graph: StateGraph,
        from_node: str,
        node_edges: list[dict[str, Any]],
    ) -> None:
        """添加并行边（fan-out）。"""
        target_nodes = [e["to"] for e in node_edges]

        def fan_out(state: dict[str, Any]) -> list[Send]:
            logger.debug(
                f"Parallel fan-out from [{from_node}] -> {target_nodes}"
            )
            return [Send(target, state) for target in target_nodes]

        graph.add_conditional_edges(from_node, fan_out)

    def _load_node_by_config(self, node_config: dict[str, Any]) -> BaseNode:
        """根据节点配置加载节点实例。"""
        node_type = node_config.get("type", "")
        node_cls: type[BaseNode] | None = NODE_TYPE_CLASSES_MAPPING.get(
            NodeType(node_type)
        )
        if node_cls is None:
            raise WorkflowConfigError(f"Node type {node_type} not found")
        node_instance = node_cls(
            node_config.get("id", ""), node_config
        )

        if hasattr(node_instance, "bind"):
            props = node_config.get("props", {})
            tool_name = props.get("name", "")

            if node_type == "tool":
                tool_class_path = props.get("class", "")
                if tool_class_path is None:
                    raise WorkflowConfigError(f"Node type {node_type} has no tool class")
                tool_instance = create_tool_instance(tool_name, tool_class_path)
                node_instance.bind(tool_name, tool_instance)

        return node_instance


def load_subgraph(workflow_id: str) -> FlowCompiler:
    """加载子工作流配置并编译。

    统一的子工作流加载入口，FlowCompiler 和 SubGraphNode 共用。
    """
    path = os.path.join(
        settings.APP.ROOT_DIR, f"flow/{workflow_id}.json"
    )
    try:
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
        compiler = FlowCompiler(config)
        compiler.compile()
        return compiler
    except FileNotFoundError as e:
        raise WorkflowConfigError(f"Workflow file not found: {path}") from e
    except json.JSONDecodeError as e:
        raise WorkflowConfigError(f"Workflow JSON error: {path}, {e}") from e
    except Exception as e:
        raise WorkflowConfigError(
            f"Failed to load subgraph '{workflow_id}': {type(e).__name__}: {e}"
        ) from e
