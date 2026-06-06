"""调度框架基础模块 — 提供 BaseTask、TaskResult、apply_yaml_config、ensure_async_run。"""

from framework.scheduler.base_task import BaseTask, TaskResult, apply_yaml_config, ensure_async_run

__all__ = ["BaseTask", "TaskResult", "apply_yaml_config", "ensure_async_run"]
