"""故障恢复管理器 — 基于检查点重建并恢复中断的编排。"""

from __future__ import annotations

import json
import logging

from framework.commons.exceptions import OrchestrationNotFoundError, RecoveryFailedError
from worker.orchestrator.checkpoint_manager import CheckpointManager
from worker.orchestrator.orchestration_tracker import OrchestrationTracker

logger = logging.getLogger(__name__)


class RecoveryManager:
    def __init__(
        self,
        checkpoint_manager: CheckpointManager,
        orchestration_tracker: OrchestrationTracker,
    ) -> None:
        self._checkpoint = checkpoint_manager
        self._tracker = orchestration_tracker

    def recover_orchestration(self, orchestration_id: str) -> str | None:
        record = self._tracker.get(orchestration_id)
        if record is None:
            raise OrchestrationNotFoundError(f"Orchestration '{orchestration_id}' not found")
        status = record.get("status")
        if status not in ("RUNNING", "INTERRUPTED", "FAILED", "FAILURE"):
            return None
        resume_from = self._checkpoint.find_resume_point(orchestration_id)
        if resume_from < 0:
            return None

        # 使用 send_task 分发恢复点之后的步骤
        steps: list[str] = json.loads(record.get("steps", "[]"))
        remaining_steps = steps[resume_from:]
        if not remaining_steps:
            raise RecoveryFailedError(f"No remaining steps to rebuild for orchestration '{orchestration_id}'")

        cycle_id = record.get("cycle_id", "")
        first_task_id = self._dispatch_remaining_steps(remaining_steps, cycle_id, orchestration_id, all_steps=steps)

        self._tracker.update_status(orchestration_id, "RUNNING")
        return first_task_id

    def scan_and_recover(self) -> list[str]:
        orchestrations = self._tracker.list_by_status("RUNNING") + self._tracker.list_by_status("INTERRUPTED")
        recovered_ids: list[str] = []
        for orch in orchestrations:
            orchestration_id = orch.get("orchestration_id", "")
            if not orchestration_id:
                continue
            try:
                task_id = self.recover_orchestration(orchestration_id)
                if task_id is not None:
                    recovered_ids.append(orchestration_id)
            except Exception:
                logger.warning("恢复编排失败: %s", orchestration_id, exc_info=True)
                continue
        return recovered_ids

    def _dispatch_remaining_steps(
        self,
        remaining_steps: list[str],
        cycle_id: str,
        orchestration_id: str,
        all_steps: list[str] | None = None,
    ) -> str:
        """通过 DAG 屏障触发器分发剩余步骤的根任务。"""
        from celery import current_app

        from worker.scheduler.context import get_dag

        dag = get_dag()
        first_task_id: str = ""
        step_index_map = {name: idx for idx, name in enumerate(all_steps)} if all_steps else {}

        for step_name in remaining_steps:
            node = dag.nodes.get(step_name)
            if node is None:
                logger.warning("恢复编排: 步骤 %s 不在 DAG 中，跳过", step_name)
                continue

            # 只分发无依赖的根任务（或依赖已满足的任务）
            # 其他任务由屏障触发器自动触发
            if node.depends_on:
                # 检查依赖是否已满足
                all_deps_done = True
                for dep in node.depends_on:
                    dep_node = dag.nodes.get(dep)
                    if dep_node is None:
                        continue
                    # 检查 Redis 中该步骤的状态
                    from framework.commons.redis_client import redis_client

                    key = f"cycle:{cycle_id}:task:{dep}"
                    data = redis_client.client.hgetall(key)  # type: ignore[union-attr]
                    if not data:
                        all_deps_done = False
                        break
                    status_val = data.get("status", data.get(b"status", b""))  # type: ignore[union-attr]
                    status_str = status_val.decode() if isinstance(status_val, bytes) else str(status_val)  # type: ignore[union-attr]
                    if status_str != "SUCCESS":
                        all_deps_done = False
                        break

                if not all_deps_done:
                    continue  # 依赖未满足，跳过（由屏障触发器后续处理）

            celery_task_name = node.celery_task_name or step_name
            queue = node.queue or "celery"
            kwargs = dict(node.kwargs or {})
            kwargs["cycle_id"] = cycle_id
            kwargs["orchestration_id"] = orchestration_id
            kwargs["dag_node_name"] = step_name
            if step_name in step_index_map:
                kwargs["step_index"] = step_index_map[step_name]

            result = current_app.send_task(
                celery_task_name,
                kwargs=kwargs,
                queue=queue,
            )
            if not first_task_id:
                first_task_id = result.id

        return first_task_id
