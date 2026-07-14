"""配置同步 — YAML 配置与数据库配置的合并。"""

from __future__ import annotations

import json
import logging
from typing import Any

from worker.models import PipelineDef

logger = logging.getLogger(__name__)


class ConfigSync:
    def __init__(self, config_dict: dict[str, Any]) -> None:
        self._config = config_dict

    async def sync_to_db(self) -> list[str]:
        synced: list[str] = []
        tasks = self._config.get("tasks", {})

        for task_id, task_def in tasks.items():
            data = {
                "description": task_def.get("description", ""),
                "config": json.dumps(task_def, ensure_ascii=False),
                "mode": task_def.get("mode", "barrier"),
                "cron": task_def.get("schedule"),
                "queue": task_def.get("queue", "celery"),
                "is_active": True,
            }
            existing = await PipelineDef.get_one_or_none(name=task_id)
            if existing is not None:
                await existing.update(data)
            else:
                await PipelineDef.create(name=task_id, **data)
            synced.append(task_id)

        logger.info("Synced %d orchestrations to db: %s", len(synced), synced)
        return synced

    async def load_from_db(self) -> dict[str, dict[str, Any]]:
        records = await PipelineDef.filter(is_active=True)
        result: dict[str, dict[str, Any]] = {}
        for record in records:
            config = json.loads(record.config) if isinstance(record.config, str) else record.config
            pipeline_name = record.name
            pipeline_mode = record.mode or "barrier"

            # 将编排步骤转换为 DAG 节点格式
            steps = config.get("steps", [])
            for step in steps:
                step_name = step["name"]
                result[step_name] = {
                    "type": "dependent",
                    "mode": pipeline_mode,
                    "pipeline_name": pipeline_name,
                    "celery_task_name": step["task"],
                    "depends_on": step.get("depends_on", []),
                    "dependency_mode": "all_success",
                    "queue": config.get("queue", "celery"),
                    "timeout": config.get("timeout", 3600),
                    "kwargs": step.get("args", {}),
                }

            # canvas 模式 + cron：注册编排级别的 cron 节点
            if pipeline_mode == "canvas" and record.cron:
                result[pipeline_name] = {
                    "type": "cron",
                    "mode": "canvas",
                    "pipeline_name": pipeline_name,
                    "celery_task_name": "worker.orchestration.trigger_pipeline",
                    "schedule": record.cron,
                    "kwargs": {"pipeline_name": pipeline_name},
                    "queue": record.queue or "celery",
                }
        logger.info("Loaded %d orchestrations from db", len(result))
        return result

    @staticmethod
    def merge_config(yaml_config: dict[str, Any], db_config: dict[str, dict[str, Any]]) -> dict[str, Any]:
        merged_tasks: dict[str, Any] = {}

        yaml_tasks = yaml_config.get("tasks", {})
        for task_id, task_def in yaml_tasks.items():
            if task_id in db_config:
                merged = dict(task_def)
                merged.update(db_config[task_id])
                merged_tasks[task_id] = merged
            else:
                merged_tasks[task_id] = task_def

        for task_id, task_def in db_config.items():
            if task_id not in merged_tasks:
                merged_tasks[task_id] = task_def

        merged = dict(yaml_config)
        merged["tasks"] = merged_tasks
        return merged
