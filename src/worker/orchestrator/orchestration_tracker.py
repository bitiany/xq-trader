"""编排记录追踪器 — 管理编排生命周期元数据（Redis + sch_task_exec）。"""

from __future__ import annotations

import json
import logging
from typing import Any

from framework.commons.redis_client import redis_client

logger = logging.getLogger(__name__)


class OrchestrationTracker:
    def __init__(self) -> None:
        self._client = redis_client.client

    def create(
        self,
        orchestration_id: str,
        workflow_type: str,
        cycle_id: str,
        task_name: str,
        steps: list[str],
    ) -> None:
        from datetime import datetime

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data: dict[str, str] = {
            "orchestration_id": orchestration_id,
            "workflow_type": workflow_type,
            "cycle_id": cycle_id,
            "task_name": task_name,
            "status": "CREATED",
            "steps": json.dumps(steps),
            "created_at": now,
            "updated_at": now,
        }
        key = f"orchestration:{orchestration_id}"
        self._client.hset(key, mapping=data)  # type: ignore[attr-defined]
        # 写入 sch_task_exec（编排父记录）
        self._write_pipeline_exec(orchestration_id, task_name, "CREATED", now)

    def update_status(self, orchestration_id: str, status: str) -> None:
        existing = self.get(orchestration_id)
        if existing is None:
            raise ValueError(f"Orchestration '{orchestration_id}' not found")
        from datetime import datetime

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        existing["status"] = status
        existing["updated_at"] = now
        key = f"orchestration:{orchestration_id}"
        self._client.hset(key, mapping=existing)  # type: ignore[attr-defined]
        # 更新 sch_task_exec
        self._write_pipeline_exec(orchestration_id, existing.get("task_name", ""), status, now)

    def get(self, orchestration_id: str) -> dict[str, str] | None:
        key = f"orchestration:{orchestration_id}"
        data = self._client.hgetall(key)  # type: ignore[union-attr]
        if not data:
            return None
        return {
            k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
            for k, v in data.items()  # type: ignore[union-attr]
        }

    def list_by_status(self, status: str) -> list[dict[str, str]]:
        raw_keys = self._client.keys("orchestration:*")  # type: ignore[union-attr]
        results: list[dict[str, str]] = []
        for key in raw_keys:  # type: ignore[union-attr]
            key_str = key.decode() if isinstance(key, bytes) else str(key)
            if key_str.endswith(":checkpoint") or key_str.endswith(":results"):
                continue
            data = self._client.hgetall(key_str)  # type: ignore[union-attr]
            data_dict = {
                k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
                for k, v in data.items()  # type: ignore[union-attr]
            }
            if data_dict and data_dict.get("status") == status:
                results.append(data_dict)
        return results

    def _write_pipeline_exec(
        self,
        orchestration_id: str,
        task_name: str,
        status: str,
        timestamp: str,
    ) -> None:
        """将编排父记录写入 sch_task_exec。"""
        from worker.executor.async_runner import async_runner

        async def _upsert() -> None:
            from worker.models import TaskExec

            data: dict[str, Any] = {"status": status}
            if status == "CREATED":
                data["started_at"] = timestamp
            elif status in ("SUCCESS", "FAILED", "INTERRUPTED"):
                data["finished_at"] = timestamp

            instance = TaskExec(
                id=orchestration_id,
                task_name=task_name,
                task_type="pipeline",
                retry_count=0,
                **data,
            )
            update_fields = [f for f in data if f != "status"] + ["status"]
            await TaskExec.bulk_create_or_update(
                [instance],
                on_conflict=["id"],
                update_fields=update_fields,
            )

        try:
            if async_runner._loop is not None and async_runner._loop.is_running():
                async_runner.run(_upsert())
            else:
                import asyncio

                asyncio.run(_upsert())
        except Exception:
            logger.warning("写入 TaskExec(编排) 失败: %s", orchestration_id, exc_info=True)
