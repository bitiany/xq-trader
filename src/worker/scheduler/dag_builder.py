"""DAG 构建器 — 从配置字典构建 DAG，支持拓扑排序和环检测。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from framework.commons.exceptions import CyclicDependencyError, UnknownDependencyError


@dataclass
class DAGNode:
    name: str
    task_type: str
    pipeline_name: str | None = None
    mode: str = "barrier"  # barrier（屏障模式）或 canvas（单任务模式）
    schedule: str | None = None
    depends_on: list[str] = field(default_factory=list)
    dependency_mode: str = "all_success"
    workflow: dict[str, Any] | None = None
    timeout: int = 3600
    retry_config: dict[str, Any] | None = None
    queue: str | None = None
    on_failure: str | None = None
    kwargs: dict[str, Any] | None = None
    celery_task_name: str | None = None
    downstream: list[str] = field(default_factory=list)


@dataclass
class DAG:
    nodes: dict[str, DAGNode] = field(default_factory=dict)

    def add_node(self, node: DAGNode) -> None:
        self.nodes[node.name] = node

    def topological_sort(self) -> list[str]:
        in_degree: dict[str, int] = {name: 0 for name in self.nodes}
        for name, node in self.nodes.items():
            for dep in node.depends_on:
                if dep in self.nodes:
                    in_degree[name] += 1

        queue: deque[str] = deque()
        for name, degree in in_degree.items():
            if degree == 0:
                queue.append(name)

        result: list[str] = []
        while queue:
            name = queue.popleft()
            result.append(name)
            for downstream_name in self.nodes[name].downstream:
                in_degree[downstream_name] -= 1
                if in_degree[downstream_name] == 0:
                    queue.append(downstream_name)

        return result

    def validate_no_cycle(self) -> None:
        sorted_nodes = self.topological_sort()
        if len(sorted_nodes) != len(self.nodes):
            visited = set(sorted_nodes)
            cycle_nodes = [name for name in self.nodes if name not in visited]
            raise CyclicDependencyError(f"Cyclic dependency detected among tasks: {cycle_nodes}")

    def get_upstream(self, task_name: str) -> list[str]:
        if task_name not in self.nodes:
            raise KeyError(f"Task not found in DAG: {task_name}")
        return list(self.nodes[task_name].depends_on)

    def get_downstream(self, task_name: str) -> list[str]:
        if task_name not in self.nodes:
            raise KeyError(f"Task not found in DAG: {task_name}")
        return list(self.nodes[task_name].downstream)


def build_dag(config_dict: dict) -> DAG:
    """从配置字典构建 DAG，验证无环。"""
    dag = DAG()
    tasks = config_dict.get("tasks", {})
    default_timeout = config_dict.get("scheduler", {}).get("default_timeout", 3600)

    for task_name, task_def in tasks.items():
        node = DAGNode(
            name=task_name,
            task_type=task_def["type"],
            pipeline_name=task_def.get("pipeline_name"),
            mode=task_def.get("mode", "barrier"),
            schedule=task_def.get("schedule"),
            depends_on=list(task_def.get("depends_on") or []),
            dependency_mode=task_def.get("dependency_mode", "all_success"),
            workflow=task_def.get("workflow"),
            timeout=task_def.get("timeout", default_timeout),
            retry_config=task_def.get("retry_config"),
            queue=task_def.get("queue"),
            on_failure=task_def.get("on_failure"),
            kwargs=task_def.get("kwargs"),
            celery_task_name=task_def.get("celery_task_name"),
        )
        dag.add_node(node)

    for name, node in dag.nodes.items():
        for dep in node.depends_on:
            if dep not in dag.nodes:
                raise UnknownDependencyError(f"Task '{name}' depends on unknown task '{dep}'")
            if name not in dag.nodes[dep].downstream:
                dag.nodes[dep].downstream.append(name)

    dag.validate_no_cycle()

    return dag
