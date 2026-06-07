"""屏障触发器 — 基于 Redis 原子计数器实现分布式屏障，支持多种依赖模式。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from framework.commons.redis_client import redis_client
from worker.scheduler.dag_builder import DAG

logger = logging.getLogger(__name__)


class BarrierResolver:
    def __init__(self, dag: DAG, dry_run: bool = False) -> None:
        self._dag = dag
        self._dry_run = dry_run
        self._dependency_strategies: dict[str, Callable[..., None]] = {
            "all_success": self._strategy_all_success,
            "all_done": self._strategy_all_done,
            "any_success": self._strategy_any_success,
        }

    def on_task_completed(self, task_name: str, cycle_id: str, status: str, **fields: Any) -> None:
        self._set_task_status(cycle_id, task_name, status, **fields)

        node = self._dag.nodes.get(task_name)
        if node is None:
            return

        # 叶子节点成功且无下游 → 检查编排是否全部完成
        if not node.downstream:
            if status == "SUCCESS":
                self._check_pipeline_complete(cycle_id)
            elif status == "FAILED":
                self._update_orchestration_status(cycle_id, "FAILED")

        for downstream_name in node.downstream:
            barrier_count = self._incr_barrier(cycle_id, downstream_name)
            downstream_node = self._dag.nodes.get(downstream_name)
            if downstream_node is None:
                continue

            upstream_count = len(downstream_node.depends_on)
            if barrier_count >= upstream_count:
                self._try_trigger_downstream(downstream_name, cycle_id)

    def _try_trigger_downstream(self, downstream_name: str, cycle_id: str) -> None:
        downstream_node = self._dag.nodes.get(downstream_name)
        if downstream_node is None:
            return

        mode = downstream_node.dependency_mode
        upstream_names = downstream_node.depends_on

        strategy = self._dependency_strategies.get(mode)
        if strategy is None:
            logger.warning("未知的依赖模式: %s, 跳过下游任务 %s", mode, downstream_name)
            return
        strategy(downstream_name, cycle_id, upstream_names)

    def _strategy_all_success(self, downstream_name: str, cycle_id: str, upstream_names: list[str]) -> None:
        all_ok = all(self._is_success(cycle_id, name) for name in upstream_names)
        if all_ok:
            self._set_barrier_status(cycle_id, downstream_name, "SATISFIED")
            self._trigger_task(downstream_name, cycle_id)
        else:
            self._set_barrier_status(cycle_id, downstream_name, "BROKEN")
            self._skip_task(downstream_name, cycle_id)
            self._update_orchestration_status(cycle_id, "FAILED")

    def _strategy_all_done(self, downstream_name: str, cycle_id: str, upstream_names: list[str]) -> None:
        self._set_barrier_status(cycle_id, downstream_name, "SATISFIED")
        self._trigger_task(downstream_name, cycle_id)

    def _strategy_any_success(self, downstream_name: str, cycle_id: str, upstream_names: list[str]) -> None:
        any_ok = any(self._is_success(cycle_id, name) for name in upstream_names)
        if any_ok:
            self._set_barrier_status(cycle_id, downstream_name, "SATISFIED")
            self._trigger_task(downstream_name, cycle_id)
        else:
            self._set_barrier_status(cycle_id, downstream_name, "BROKEN")
            self._skip_task(downstream_name, cycle_id)
            self._update_orchestration_status(cycle_id, "FAILED")

    def _trigger_task(self, task_name: str, cycle_id: str) -> None:
        if self._dry_run:
            return

        from celery import current_app

        node = self._dag.nodes.get(task_name)
        if node is None:
            return

        celery_task_name = node.celery_task_name or task_name
        queue = node.queue or "celery"
        kwargs = dict(node.kwargs or {})
        kwargs["cycle_id"] = cycle_id
        kwargs["dag_node_name"] = task_name
        # 传递 orchestration_id（从上游任务的 Redis 状态中获取）
        orch_id = self._get_orchestration_id(cycle_id)
        if orch_id:
            kwargs["orchestration_id"] = orch_id
            # 注入 step_index（从编排记录的步骤列表中查找）
            step_index = self._get_step_index(orch_id, task_name)
            if step_index is not None:
                kwargs["step_index"] = step_index
        current_app.send_task(
            celery_task_name,
            kwargs=kwargs,
            queue=queue,
            soft_time_limit=node.timeout,
            time_limit=node.timeout + 60,
        )

    def _skip_task(self, task_name: str, cycle_id: str) -> None:
        self._set_task_status(cycle_id, task_name, "SKIPPED")

        if self._dry_run:
            return

        node = self._dag.nodes.get(task_name)
        if node is None:
            return

        if node.on_failure:
            from celery import current_app

            current_app.send_task(
                node.on_failure,
                args=[cycle_id, task_name],
                queue="celery",
            )

    def write_barrier_configs(self) -> None:
        for name, node in self._dag.nodes.items():
            if not node.depends_on:
                continue
            upstream_count = len(node.depends_on)
            self._set_barrier_config(name, upstream_count, node.dependency_mode)

    # ── Redis 操作（基于当前项目的 redis_client）──

    def _set_task_status(self, cycle_id: str, task_name: str, status: str, **fields: Any) -> None:
        key = f"cycle:{cycle_id}:task:{task_name}"
        mapping: dict[str, str] = {"status": status}
        for k, v in fields.items():
            mapping[k] = str(v) if not isinstance(v, str) else v
        redis_client.client.hset(key, mapping=mapping)  # type: ignore[attr-defined]
        redis_client.client.expire(key, 7 * 24 * 3600)  # type: ignore[attr-defined]

    def _get_orchestration_id(self, cycle_id: str) -> str | None:
        """从 Redis 中获取当前周期的 orchestration_id。"""
        key = f"cycle:{cycle_id}:orchestration_id"
        val = redis_client.client.get(key)  # type: ignore[attr-defined]
        if val is None:
            return None
        return val.decode() if isinstance(val, bytes) else str(val)  # type: ignore[union-attr]

    def _get_step_index(self, orchestration_id: str, task_name: str) -> int | None:
        """从编排记录中获取步骤索引。"""
        try:
            from worker.orchestrator.orchestration_tracker import OrchestrationTracker

            tracker = OrchestrationTracker()
            record = tracker.get(orchestration_id)
            if record is None:
                return None
            import json

            steps: list[str] = json.loads(record.get("steps", "[]"))
            if task_name in steps:
                return steps.index(task_name)
        except Exception:
            logger.warning("获取步骤索引失败: orch=%s task=%s", orchestration_id, task_name, exc_info=True)
        return None

    def _update_orchestration_status(self, cycle_id: str, status: str) -> None:
        """更新编排状态到 Redis 和 sch_task_exec。"""
        orch_id = self._get_orchestration_id(cycle_id)
        if not orch_id:
            return
        try:
            from worker.orchestrator.orchestration_tracker import OrchestrationTracker

            tracker = OrchestrationTracker()
            tracker.update_status(orch_id, status)
        except Exception:
            logger.warning("更新编排状态失败: orch=%s status=%s", orch_id, status, exc_info=True)

    def _check_pipeline_complete(self, cycle_id: str) -> None:
        """检查编排是否全部完成（所有叶子节点都成功）。"""
        orch_id = self._get_orchestration_id(cycle_id)
        if not orch_id:
            return
        try:
            from worker.scheduler.context import get_pipeline_steps

            pipeline_steps = get_pipeline_steps()
            # 找到该编排的所有叶子节点
            for pipeline_name, step_names in pipeline_steps.items():
                leaf_nodes: list[str] = []
                all_done = True
                for step_name in step_names:
                    node = self._dag.nodes.get(step_name)
                    if node is None:
                        continue
                    if not node.downstream:
                        leaf_nodes.append(step_name)
                        # 检查叶子节点状态
                        key = f"cycle:{cycle_id}:task:{step_name}"
                        data = redis_client.client.hgetall(key)  # type: ignore[union-attr]
                        if not data:
                            all_done = False
                            continue
                        status_val = data.get("status", data.get(b"status", b""))  # type: ignore[union-attr]
                        status_str = status_val.decode() if isinstance(status_val, bytes) else str(status_val)  # type: ignore[union-attr]
                        if status_str != "SUCCESS":
                            all_done = False
                if leaf_nodes and all_done:
                    self._update_orchestration_status(cycle_id, "SUCCESS")
                    return
        except Exception:
            logger.warning("检查编排完成状态失败: orch=%s", orch_id, exc_info=True)

    def _is_success(self, cycle_id: str, task_name: str) -> bool:
        key = f"cycle:{cycle_id}:task:{task_name}"
        data = redis_client.client.hgetall(key)  # type: ignore[union-attr]
        return bool(data and data.get(b"status", b"") == b"SUCCESS" or data.get("status", "") == "SUCCESS")  # type: ignore[union-attr]

    def _incr_barrier(self, cycle_id: str, downstream: str) -> int:
        key = f"cycle:{cycle_id}:barrier:{downstream}"
        count = redis_client.client.incr(key)  # type: ignore[attr-defined]
        redis_client.client.expire(key, 7 * 24 * 3600)  # type: ignore[attr-defined]
        return count  # type: ignore[return-value]

    def _set_barrier_status(self, cycle_id: str, downstream: str, status: str) -> None:
        key = f"cycle:{cycle_id}:barrier:{downstream}:status"
        redis_client.client.set(key, status, ex=7 * 24 * 3600)  # type: ignore[attr-defined]

    def _set_barrier_config(self, downstream: str, upstream_count: int, mode: str) -> None:
        key = f"barrier:config:{downstream}"
        redis_client.client.hset(key, mapping={"upstream_count": str(upstream_count), "mode": mode})  # type: ignore[attr-defined]
