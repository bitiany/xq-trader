"""SPI 插件发现与注册 — 扫描插件目录，解析 plugin.yaml，导入 BaseTask 子类，动态注册 Celery task。"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from framework.commons.logger import get_logger
from framework.scheduler.base_task import BaseTask, apply_yaml_config, ensure_async_run

logger = get_logger("PLUGIN")


@dataclass
class PluginManifest:
    """插件清单 — 从 plugin.yaml 解析。"""

    name: str = ""
    celery_task_name: str = ""
    version: str = "1.0.0"
    task_name: str = ""
    task_name_en: str = ""
    description: str = ""
    category: str = "compute"
    task_type: str = "on_demand"
    queue: str = "celery"
    timeout: int = 300
    retry_config: dict = field(default_factory=dict)
    params_schema: dict = field(default_factory=dict)
    schedule: str = ""
    # 运行时属性
    module_path: str = ""
    task_cls: type[BaseTask] | None = None


# 全局注册表
_registry: dict[str, PluginManifest] = {}


def autodiscover(plugins_dir: str) -> None:
    """
    扫描 plugins_dir 下所有子目录，
    解析 plugin.yaml，导入 task.py 中的 BaseTask 子类，
    合并 yaml 配置，注册到 Celery + DB + Beat。
    """
    plugins_path = Path(plugins_dir)
    if not plugins_path.exists():
        logger.warning("插件目录不存在: %s", plugins_dir)
        return

    for plugin_dir in sorted(plugins_path.iterdir()):
        if not plugin_dir.is_dir() or plugin_dir.name.startswith("_"):
            continue
        yaml_path = plugin_dir / "plugin.yaml"
        if not yaml_path.exists():
            logger.warning("跳过无 plugin.yaml 的目录: %s", plugin_dir.name)
            continue

        manifest = _parse_manifest(yaml_path)
        manifest.module_path = f"worker.plugins.{plugin_dir.name}"

        # 导入 task.py 中的 BaseTask 子类
        task_cls = _import_task_class(manifest.module_path, manifest.name)
        if task_cls is None:
            continue

        manifest.task_cls = task_cls

        # 合并 yaml 配置到类属性
        apply_yaml_config(task_cls, manifest)

        # 异步桥接
        ensure_async_run(task_cls)

        _register(manifest)


def _import_task_class(module_path: str, plugin_name: str) -> type[BaseTask] | None:
    """从 task.py 模块中找到 BaseTask 子类。"""
    try:
        task_module = importlib.import_module(f"{module_path}.task")
    except ImportError as e:
        logger.warning("插件 %s 的 task.py 导入失败: %s", plugin_name, e)
        return None

    for attr_name in dir(task_module):
        attr = getattr(task_module, attr_name)
        if (
            isinstance(attr, type)
            and issubclass(attr, BaseTask)
            and attr is not BaseTask
            and getattr(attr, "task_name", "") != ""
        ):
            return attr

    logger.warning("插件 %s 的 task.py 中未找到 BaseTask 子类", plugin_name)
    return None


def _parse_manifest(yaml_path: Path) -> PluginManifest:
    """解析 plugin.yaml 文件。"""
    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return PluginManifest(
        name=data.get("name", yaml_path.parent.name),
        celery_task_name=data.get("celery_task_name", ""),
        version=data.get("version", "1.0.0"),
        task_name=data.get("task_name", ""),
        task_name_en=data.get("task_name_en", ""),
        description=data.get("description", ""),
        category=data.get("category", "compute"),
        task_type=data.get("task_type", "on_demand"),
        queue=data.get("queue", "celery"),
        timeout=data.get("timeout", 300),
        retry_config=data.get("retry_config", {}),
        params_schema=data.get("params_schema", {}),
        schedule=data.get("schedule", ""),
    )


def _register(manifest: PluginManifest) -> None:
    """注册插件到全局表 + Celery + DB + Beat。"""
    task_name = manifest.celery_task_name
    if not task_name:
        logger.warning("插件 %s 缺少 celery_task_name，跳过", manifest.name)
        return

    _registry[task_name] = manifest

    # 注册到 Celery
    from worker.celery_app import celery_app

    celery_app.register_task(manifest.task_cls)  # type: ignore[arg-type]

    # upsert 到 DB（TaskDef）
    _sync_task_def(manifest)

    # 如果有调度配置，注册到 Beat
    if manifest.schedule and manifest.task_type == "scheduled":
        _register_beat(task_name, manifest)

    logger.info(
        "注册插件: %s → %s (queue=%s, cron=%s)",
        manifest.name,
        task_name,
        manifest.queue,
        manifest.schedule or "无",
    )


def _register_beat(task_name: str, manifest: PluginManifest) -> None:
    """将调度配置注册到 Celery Beat schedule。"""
    from celery.schedules import crontab

    from worker.celery_app import celery_app

    cron_params = _parse_cron(manifest.schedule)
    celery_app.conf.beat_schedule[task_name] = {
        "task": task_name,
        "schedule": crontab(**cron_params),
        "kwargs": {},
        "options": {"queue": manifest.queue},
    }


def _parse_cron(expr: str) -> dict[str, str]:
    """解析 cron 表达式。"""
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {expr}")
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day_of_month": parts[2],
        "month_of_year": parts[3],
        "day_of_week": parts[4],
    }


def _sync_task_def(manifest: PluginManifest) -> None:
    """启动时 upsert 到 TaskDef 表。"""
    from worker.models import TaskDef

    async def _upsert() -> None:
        existing = await TaskDef.get_one_or_none(name=manifest.celery_task_name)
        data = {
            "name": manifest.celery_task_name,
            "description": manifest.description or manifest.task_name,
            "module": manifest.module_path,
            "time_limit": manifest.timeout,
            "max_retries": manifest.retry_config.get("max_retries", 3),
            "prevent_concurrent": True,
            "is_active": True,
        }
        if existing:
            await existing.update(data)
        else:
            await TaskDef.create(**data)

    try:
        from worker.executor.async_runner import async_runner

        if async_runner._loop is not None and async_runner._loop.is_running():
            async_runner.run(_upsert())
        else:
            import asyncio

            asyncio.run(_upsert())
    except Exception:
        logger.warning("同步 TaskDef 到 DB 失败: %s", manifest.name, exc_info=True)


def get_manifest(task_name: str) -> PluginManifest | None:
    """获取已注册的插件清单。"""
    return _registry.get(task_name)


def get_task_cls(task_name: str) -> type[BaseTask] | None:
    """获取已注册的任务类。"""
    manifest = _registry.get(task_name)
    return manifest.task_cls if manifest else None


def list_plugins() -> dict[str, PluginManifest]:
    """获取所有已注册的插件。"""
    return dict(_registry)
