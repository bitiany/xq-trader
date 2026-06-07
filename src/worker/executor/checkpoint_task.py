"""检查点任务包装器 — 在业务函数外包装检查点保存和 sch_task_exec 写入。"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class CheckpointManagerProtocol(Protocol):
    def save_checkpoint(self, orchestration_id: str, step_index: int, status: str) -> None: ...

    def save_result(self, orchestration_id: str, step_index: int, result: Any) -> None: ...


class CheckpointTask:
    """在业务函数外包装检查点保存 + sch_task_exec 写入。

    每个步骤执行后：
    1. 保存检查点到 Redis（用于断点续跑）
    2. 写入 sch_task_exec（用于执行历史查询）
    """

    def __init__(
        self,
        step_name: str,
        step_index: int,
        business_func: Callable[..., Any],
        checkpoint_manager: CheckpointManagerProtocol,
        orchestration_id: str,
        parent_id: str | None = None,
    ) -> None:
        self._step_name = step_name
        self._step_index = step_index
        self._business_func = business_func
        self._checkpoint_manager = checkpoint_manager
        self._orchestration_id = orchestration_id
        self._parent_id = parent_id

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        start_time = time.monotonic()
        try:
            result = self._business_func(*args, **kwargs)
            self._checkpoint_manager.save_checkpoint(self._orchestration_id, self._step_index, "SUCCESS")
            self._checkpoint_manager.save_result(self._orchestration_id, self._step_index, result)
            # 写入 sch_task_exec
            duration_ms = int((time.monotonic() - start_time) * 1000)
            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._write_task_exec("SUCCESS", str(result), started_at, finished_at, duration_ms)
            return result
        except Exception:
            self._checkpoint_manager.save_checkpoint(self._orchestration_id, self._step_index, "FAILED")
            duration_ms = int((time.monotonic() - start_time) * 1000)
            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._write_task_exec("FAILURE", "", started_at, finished_at, duration_ms)
            raise

    def _write_task_exec(
        self,
        status: str,
        result: str,
        started_at: str,
        finished_at: str,
        duration_ms: int,
    ) -> None:
        """将步骤执行记录写入 sch_task_exec。"""
        from worker.executor.async_runner import async_runner

        async def _upsert() -> None:
            from worker.models import TaskExec

            task_id = f"{self._orchestration_id}:{self._step_index}"
            instance = TaskExec(
                id=task_id,
                task_name=self._step_name,
                task_type="task",
                status=status,
                result=result,
                retry_count=0,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
                parent_id=self._parent_id,
            )
            await TaskExec.bulk_create_or_update(
                [instance],
                on_conflict=["id"],
                update_fields=["status", "result", "started_at", "finished_at", "duration_ms"],
            )

        try:
            if async_runner.is_running:
                async_runner.run(_upsert())
            else:
                logger.warning(
                    "AsyncTaskRunner 未启动，跳过写入 TaskExec: %s:%s",
                    self._orchestration_id, self._step_index,
                )
        except Exception:
            logger.warning("写入 TaskExec 失败: %s:%s", self._orchestration_id, self._step_index, exc_info=True)
