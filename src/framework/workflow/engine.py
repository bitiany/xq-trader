"""工作流引擎 — 基于 LangGraph 的 DAG 执行引擎。

职责：
- 管理工作流的运行时执行（invoke / resume）
- 构建初始状态和提取输出
- 管理 checkpoint 和进度追踪
- 通过缓存池避免重复编译相同 flow_id

图编译逻辑委托给 FlowCompiler，FlowEngine 不再直接构建图。
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import uuid
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langgraph.config import RunnableConfig
from langgraph.types import Command

from framework.commons.exceptions import WorkflowResumeError
from framework.commons.logger import get_logger
from framework.workflow.compiler import FlowCompiler
from framework.workflow.progress import (
    INVOKE_TIMEOUT_SECONDS,
    ProgressCallbackHandler,
    ProgressManager,
)

logger = get_logger(__name__)

# FlowCompiler 缓存池：flow_id -> FlowCompiler，避免重复编译
_compiler_cache: dict[str, FlowCompiler] = {}


class FlowEngine:
    """工作流执行引擎。

    通过 FlowCompiler 编译图配置，然后提供同步/异步执行和恢复接口。
    """

    def __init__(
        self,
        config: dict[str, Any],
        checkpointer: Any | None = None,
    ) -> None:
        flow_id = config.get("id", "")
        cached = _compiler_cache.get(flow_id) if flow_id else None

        if cached is not None:
            self._compiler = cached
            logger.debug(f"FlowEngine [{flow_id}] using cached compiler")
        else:
            self._compiler = FlowCompiler(config)
            self._compiler.compile(checkpointer)
            if flow_id:
                _compiler_cache[flow_id] = self._compiler

        self.flow_id = self._compiler.flow_id

    @classmethod
    def from_compiler(cls, compiler: FlowCompiler) -> FlowEngine:
        """从已编译的 FlowCompiler 创建引擎实例（避免重复编译）。"""
        engine = cls.__new__(cls)
        engine._compiler = compiler
        engine.flow_id = compiler.flow_id
        return engine

    @property
    def graph(self) -> Any:
        """编译后的 LangGraph 图。"""
        return self._compiler.compiled_graph

    @property
    def node_configs(self) -> dict[str, dict[str, Any]]:
        return self._compiler.node_configs

    @property
    def executors(self) -> dict[str, Any]:
        return self._compiler.executors

    @property
    def sub_processes(self) -> list[FlowCompiler]:
        return self._compiler.sub_processes

    def length(self) -> int:
        """计算工作流节点总数（含子工作流）。"""
        return self._compiler.total_nodes

    def _build_runnable_config(
        self, config: dict[str, Any] | None = None
    ) -> RunnableConfig:
        """构建 LangGraph 运行配置。"""
        thread_id = (config or {}).get("thread_id") or str(uuid.uuid4())
        total_nodes = self.length()
        execute_id = (config or {}).get("execute_id", "")
        is_subflow = (config or {}).get("parent_flow_id") is not None

        progress_manager = ProgressManager(
            total_nodes=total_nodes,
            flow_name=self.flow_id,
            execute_id=execute_id,
        )

        callbacks_list: list[BaseCallbackHandler] = [
            ProgressCallbackHandler(
                flow_name=self.flow_id,
                progress_manager=progress_manager,
                is_subflow=is_subflow,
            )
        ]

        runnable_config: RunnableConfig = {
            "run_name": self.flow_id,
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 1000,
            "tags": [],
            "metadata": {
                "nodes": list(self.graph.nodes.keys()),
                "execute_id": execute_id,
            },
            "callbacks": callbacks_list,
        }
        return runnable_config

    def _build_initial_state(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """构建工作流初始状态。"""
        state: dict[str, Any] = {
            "variables": {},
            "context": {},
            "content": "",
            "execute_id": inputs.get("execute_id", ""),
            "workspace_id": inputs.get("workspace_id", ""),
            "parallel_outputs": {},
            "interrupt_info": {},
        }
        input_schema = self._compiler._input_schema
        if input_schema:
            for target_key, source_key in input_schema.items():
                if source_key in inputs:
                    state["variables"][target_key] = inputs[source_key]
                else:
                    state["variables"][target_key] = inputs.get(target_key)
        else:
            for k, v in inputs.items():
                if k not in ("execute_id", "workspace_id"):
                    state["variables"][k] = v
        return state

    def _extract_output(self, result_state: dict[str, Any]) -> dict[str, Any]:
        """从最终状态中提取输出。"""
        output_schema = self._compiler._output_schema
        if not output_schema:
            return dict(result_state.get("variables", {}))
        output: dict[str, Any] = {}
        variables = result_state.get("variables", {})
        for target_key, source_key in output_schema.items():
            if source_key in variables:
                output[target_key] = variables[source_key]
            elif source_key in result_state:
                output[target_key] = result_state[source_key]
        return output

    async def ainvoke(
        self,
        state: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        *,
        inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """异步执行工作流。"""
        try:
            if state is None and inputs is not None:
                state = self._build_initial_state(inputs)
            elif state is None:
                state = self._build_initial_state({})

            execute_id = (config or {}).get("execute_id", state.get("execute_id", ""))
            workspace_id = (config or {}).get("workspace_id", state.get("workspace_id", ""))
            state["execute_id"] = execute_id
            state["workspace_id"] = workspace_id
            state.setdefault("parallel_outputs", {})
            state.setdefault("interrupt_info", {})

            logger.info(
                f"FlowEngine [{self.flow_id}] ainvoke | "
                f"execute_id: {execute_id} | "
                f"nodes: {len(self.node_configs)}"
            )

            result = await self.graph.ainvoke(state, self._build_runnable_config(config))
            return dict(result)

        except Exception as e:
            logger.error(
                f"FlowEngine [{self.flow_id}] execution failed: {e}",
                exc_info=True,
            )
            raise

    async def aresume(
        self,
        resume_value: Any,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """异步恢复中断的工作流。"""
        thread_id = (config or {}).get("thread_id")
        if not thread_id:
            raise WorkflowResumeError("thread_id is required for aresume")

        runnable_config = self._build_runnable_config(config)
        command: Command[Any] = Command(resume=resume_value)

        logger.info(
            f"FlowEngine [{self.flow_id}] aresume | "
            f"thread_id: {thread_id} | "
            f"resume_value type: {type(resume_value).__name__}"
        )

        result = await self.graph.ainvoke(command, runnable_config)
        return dict(result)

    def invoke(
        self,
        state: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        *,
        inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """同步执行工作流（自动处理事件循环）。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            def run_async_in_thread() -> dict[str, Any]:
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(
                        self.ainvoke(state, config, inputs=inputs)
                    )
                finally:
                    new_loop.close()

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(run_async_in_thread)
                return future.result(timeout=INVOKE_TIMEOUT_SECONDS)
        else:
            new_loop = asyncio.new_event_loop()
            try:
                return new_loop.run_until_complete(
                    self.ainvoke(state, config, inputs=inputs)
                )
            finally:
                new_loop.close()
