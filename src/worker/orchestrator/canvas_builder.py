"""Celery Canvas 工作流构建器 — 将工作流定义或 DAG 转换为 Celery Canvas 原语。"""

from __future__ import annotations

import logging
from typing import Any

from celery import Signature, chain, chord, group

logger = logging.getLogger(__name__)


class CanvasBuilder:
    def __init__(self, task_registry: dict[str, Any]) -> None:
        self._task_registry = task_registry

    def _sig(self, task_name: str, prev_result: Any = None) -> Signature:
        if task_name not in self._task_registry:
            raise ValueError(f"Task '{task_name}' not found in registry")
        task = self._task_registry[task_name]
        if isinstance(task, Signature):
            # 已经是 Signature（可能包含 kwargs），克隆并注入 prev_result
            if prev_result is not None:
                return task.clone(args=(prev_result,) + task.args)
            return task.clone()
        # 是 Celery Task 类
        if prev_result is not None:
            return task.s(prev_result)  # type: ignore[no-any-return]
        return task.s()  # type: ignore[no-any-return]

    def _signature_of(self, task_name: str) -> Signature:
        """获取任务的 Signature（不传递前一步结果）。"""
        task = self._task_registry.get(task_name)
        if task is None:
            raise ValueError(f"Task '{task_name}' not found in registry")
        if isinstance(task, Signature):
            return task.clone()
        return task.s()  # type: ignore[no-any-return]

    def build_chain(self, steps: list[str], prev_result: Any = None) -> chain:
        if not steps:
            raise ValueError("Chain requires at least one step")
        logger.debug("Building chain: %s", steps)
        signatures = []
        for i, step in enumerate(steps):
            if i == 0 and prev_result is not None:
                signatures.append(self._sig(step, prev_result))
            else:
                signatures.append(self._sig(step))
        return chain(*signatures)

    def build_group(self, tasks: list[str]) -> group:
        if not tasks:
            raise ValueError("Group requires at least one task")
        logger.debug("Building group: %s", tasks)
        signatures = [self._sig(t) for t in tasks]
        return group(*signatures)

    def build_chord(self, header: list[str], body: str) -> chord:
        if not header:
            raise ValueError("Chord header requires at least one task")
        logger.debug("Building chord: header=%s, body=%s", header, body)
        header_sigs = [self._sig(t) for t in header]
        body_sig = self._sig(body)
        return chord(header_sigs, body_sig)

    def build_from_workflow(self, workflow: dict, prev_result: Any = None) -> Signature:
        workflow_type = workflow.get("type")
        logger.info("Building from workflow: type=%s", workflow_type)
        if workflow_type == "chain":
            steps = workflow.get("steps", [])
            return self.build_chain(steps, prev_result)
        elif workflow_type == "group":
            tasks = workflow.get("tasks", [])
            return self.build_group(tasks)
        elif workflow_type == "chord":
            header = workflow.get("header", [])
            body = workflow.get("body", "")
            return self.build_chord(header, body)
        else:
            raise ValueError(f"Unknown workflow type: {workflow_type}")

    def build_from_dag(self, dag: Any, step_names: list[str]) -> Signature:
        """从 DAG 拓扑构建 Canvas 工作流。

        策略：
        1. 按拓扑层级分组（同一层级的任务并行执行）
        2. 层级之间用 chain 串行
        3. 同一层级内的多个任务用 group 并行
        4. 如果并行任务有共同的下游，使用 chord 汇聚
        """
        # 只考虑属于该编排的步骤
        nodes = {name: dag.nodes[name] for name in step_names if name in dag.nodes}

        # 计算每个节点的拓扑层级（最长路径长度）
        levels: dict[str, int] = {}
        sorted_names = dag.topological_sort()

        for name in sorted_names:
            if name not in nodes:
                continue
            node = nodes[name]
            if not node.depends_on or all(dep not in nodes for dep in node.depends_on):
                levels[name] = 0
            else:
                levels[name] = max(
                    levels.get(dep, 0) for dep in node.depends_on if dep in nodes
                ) + 1

        # 按层级分组
        max_level = max(levels.values()) if levels else 0
        level_groups: dict[int, list[str]] = {}
        for name, level in levels.items():
            level_groups.setdefault(level, []).append(name)

        if not level_groups:
            raise ValueError("DAG has no nodes to build canvas from")

        logger.info("Building from DAG: steps=%d, levels=%d", len(levels), max_level + 1)

        canvas_parts: list[Any] = []
        for level in range(max_level + 1):
            tasks_at_level = level_groups.get(level, [])
            if not tasks_at_level:
                continue

            if len(tasks_at_level) == 1:
                # 单任务 — 直接添加
                canvas_parts.append(self._signature_of(tasks_at_level[0]))
            else:
                # 多任务 — 检查是否有共同下游需要汇聚
                next_level = level + 1
                next_tasks = level_groups.get(next_level, [])

                if next_tasks:
                    # 有下游 — 使用 chord 汇聚
                    # header = 当前层级的并行任务, body = 下游的第一个任务
                    # 但 chord 只支持一个 body，所以需要特殊处理
                    # 简化策略：当前层级用 group，整体用 chain
                    canvas_parts.append(group(*[self._signature_of(t) for t in tasks_at_level]))
                else:
                    # 叶子节点 — 用 group 并行
                    canvas_parts.append(group(*[self._signature_of(t) for t in tasks_at_level]))

        if len(canvas_parts) == 1:
            return canvas_parts[0]  # type: ignore[return-value, no-any-return]
        return chain(*canvas_parts)
