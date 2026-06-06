"""Cron 调度器 — 将 DAG 中的 cron 任务注册到 Celery Beat。"""

from __future__ import annotations

import logging

from celery import Celery
from celery.schedules import crontab

from worker.scheduler.dag_builder import DAG

logger = logging.getLogger(__name__)


class CronScheduler:
    def __init__(self, celery_app: Celery) -> None:
        self._app = celery_app

    def register_cron_tasks(self, dag: DAG) -> None:
        beat_schedule: dict = {}
        for name, node in dag.nodes.items():
            if node.task_type != "cron" or not node.schedule:
                continue
            beat_schedule[name] = {
                "task": node.celery_task_name or name,
                "schedule": self._parse_cron(node.schedule),
                "args": (),
                "kwargs": dict(node.kwargs or {}),
                "options": {"queue": node.queue or "celery"},
            }

        current_config = self._app.conf.beat_schedule or {}
        current_config.update(beat_schedule)
        self._app.conf.beat_schedule = current_config
        logger.info("Registered %d cron tasks", len(beat_schedule))

    def update_cron_task(self, task_name: str, schedule: str) -> None:
        current_config = self._app.conf.beat_schedule or {}
        if task_name not in current_config:
            raise KeyError(f"Cron task not found in beat schedule: {task_name}")
        current_config[task_name]["schedule"] = self._parse_cron(schedule)
        self._app.conf.beat_schedule = current_config
        logger.info("Updated cron task: %s", task_name)

    def remove_cron_task(self, task_name: str) -> None:
        current_config = self._app.conf.beat_schedule or {}
        if task_name not in current_config:
            raise KeyError(f"Cron task not found in beat schedule: {task_name}")
        del current_config[task_name]
        self._app.conf.beat_schedule = current_config
        logger.info("Removed cron task: %s", task_name)

    @staticmethod
    def _parse_cron(expression: str) -> crontab:
        parts = expression.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression (expected 5 fields): {expression}")
        return crontab(
            minute=parts[0],
            hour=parts[1],
            day_of_month=parts[2],
            month_of_year=parts[3],
            day_of_week=parts[4],
        )
