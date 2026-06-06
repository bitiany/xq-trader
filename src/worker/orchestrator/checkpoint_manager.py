"""检查点管理器 — 管理编排步骤的状态和结果持久化（Redis）。"""

from __future__ import annotations

import logging
from typing import Any

from framework.commons.redis_client import redis_client

logger = logging.getLogger(__name__)


class CheckpointManager:
    def __init__(self) -> None:
        self._client = redis_client.client

    def save_checkpoint(self, orchestration_id: str, step_index: int, status: str) -> None:
        key = f"orchestration:{orchestration_id}:checkpoint"
        self._client.hset(key, str(step_index), status)  # type: ignore[attr-defined]
        logger.debug(
            "Checkpoint saved: orchestration_id=%s, step_index=%d, status=%s",
            orchestration_id, step_index, status,
        )

    def save_result(self, orchestration_id: str, step_index: int, result: Any) -> None:
        import json

        key = f"orchestration:{orchestration_id}:results"
        self._client.hset(key, str(step_index), json.dumps(result, default=str))  # type: ignore[attr-defined]
        logger.debug("Result saved: orchestration_id=%s, step_index=%d", orchestration_id, step_index)

    def read_checkpoint(self, orchestration_id: str) -> dict[int, str]:
        key = f"orchestration:{orchestration_id}:checkpoint"
        raw = self._client.hgetall(key)  # type: ignore[union-attr]
        result = {
            int(k if isinstance(k, str) else k.decode()): (v if isinstance(v, str) else v.decode())
            for k, v in raw.items()  # type: ignore[union-attr]
        }
        logger.debug("Checkpoint read: orchestration_id=%s, checkpoints=%d", orchestration_id, len(result))
        return result

    def read_step_result(self, orchestration_id: str, step_index: int) -> Any | None:
        import json

        key = f"orchestration:{orchestration_id}:results"
        data = self._client.hget(key, str(step_index))  # type: ignore[union-attr]
        if data is None:
            return None
        return json.loads(data if isinstance(data, str) else data.decode())  # type: ignore[attr-defined]

    def find_resume_point(self, orchestration_id: str) -> int:
        checkpoint = self.read_checkpoint(orchestration_id)
        if not checkpoint:
            return 0
        max_index = max(checkpoint.keys())
        for i in range(max_index + 2):
            if checkpoint.get(i) != "SUCCESS":
                logger.info("Resume point found: orchestration_id=%s, resume_from=%d", orchestration_id, i)
                return i
        resume = max_index + 1
        logger.info("Resume point found: orchestration_id=%s, resume_from=%d", orchestration_id, resume)
        return resume
