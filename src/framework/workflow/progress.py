"""工作流进度追踪。"""
from __future__ import annotations

import threading
import time
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from framework.commons.logger import get_logger

logger = get_logger(__name__)

DEFAULT_RECURSION_LIMIT = 1000
INVOKE_TIMEOUT_SECONDS = 300


class ProgressManager:
    """工作流执行进度管理器。

    改进：使用 set 跟踪已完成节点，避免并行场景下重复计数。
    """

    def __init__(
        self,
        total_nodes: int = 0,
        flow_name: str = "",
        execute_id: str = "",
    ) -> None:
        self.total_nodes = total_nodes
        self.completed_nodes = 0
        self.flow_stack: list[str] = [flow_name] if flow_name else []
        self.execute_id = execute_id
        self.start_time = time.time() if total_nodes > 0 else 0.0
        self._lock = threading.Lock()
        self._completed_set: set[str] = set()

    def start(
        self,
        total_nodes: int,
        flow_name: str = "main",
        execute_id: str = "",
    ) -> None:
        with self._lock:
            self.total_nodes = total_nodes
            self.completed_nodes = 0
            self.flow_stack = [flow_name]
            self.execute_id = execute_id
            self.start_time = time.time()
            self._completed_set.clear()

        tag = f" | exec: {execute_id}" if execute_id else ""
        logger.info(f"Workflow started{tag} | Flow: {flow_name} | Nodes: {total_nodes}")

    def push_flow(self, flow_name: str) -> None:
        with self._lock:
            self.flow_stack.append(flow_name)
        tag = f"[{self.execute_id}] " if self.execute_id else ""
        logger.debug(f"{tag}Enter subflow: {flow_name}")

    def pop_flow(self) -> None:
        with self._lock:
            if len(self.flow_stack) > 1:
                self.flow_stack.pop()

    def get_current_flow_path(self) -> str:
        return " -> ".join(self.flow_stack)

    def update_progress(self, node_name: str, duration: float = 0) -> None:
        with self._lock:
            # 去重：并行场景下同一节点可能被多次回调
            if node_name in self._completed_set:
                return
            self._completed_set.add(node_name)
            self.completed_nodes = len(self._completed_set)
            progress_pct = (
                self.completed_nodes / self.total_nodes * 100
                if self.total_nodes > 0
                else 0
            )

        display_name = f"{self.get_current_flow_path()}:{node_name}"
        tag = f"[{self.execute_id}] " if self.execute_id else ""

        logger.info(
            f"{tag}[{self.completed_nodes}/{self.total_nodes}] ({progress_pct:.0f}%) "
            f"Node done: {display_name} | Duration: {duration:.2f}s"
        )

        if self.completed_nodes >= self.total_nodes:
            total_duration = time.time() - self.start_time
            logger.info(
                f"{tag}Workflow completed | Flow: {self.flow_stack[0]} | "
                f"Total: {total_duration:.2f}s | "
                f"Avg per node: {total_duration / self.total_nodes:.2f}s"
            )


class ProgressCallbackHandler(BaseCallbackHandler):
    """LangGraph 回调处理器，追踪节点执行进度。"""

    def __init__(
        self,
        flow_name: str,
        progress_manager: ProgressManager | None = None,
        is_subflow: bool = False,
    ) -> None:
        super().__init__()
        self.flow_name = flow_name
        self.is_subflow = is_subflow
        self.progress_manager = progress_manager or ProgressManager()
        self.start_time = 0.0
        self.node_name: str | None = None

        if self.is_subflow:
            self.progress_manager.push_flow(flow_name)

    def on_chain_start(
        self, serialized: dict[str, Any], inputs: dict[str, Any], **kwargs: Any
    ) -> None:
        if "langgraph_node" not in kwargs.get("metadata", {}):
            return
        self.start_time = time.time()
        self.node_name = kwargs["metadata"]["langgraph_node"]

    def on_chain_end(self, outputs: dict[str, Any], **kwargs: Any) -> None:
        if not self.node_name:
            return

        duration = time.time() - self.start_time

        if not (self.is_subflow and self.node_name == "end"):
            self.progress_manager.update_progress(self.node_name, duration)

        if self.is_subflow and self.node_name == "end":
            self.progress_manager.pop_flow()

        self.node_name = None
