"""Celery 实例与配置 — Worker 服务的调度核心。"""

from __future__ import annotations

from celery import Celery

from framework.config.settings import settings


def _build_broker_url() -> str:
    redis = settings.REDIS
    celery = settings.CELERY
    if celery.CELERY_BROKER_URL:
        return celery.CELERY_BROKER_URL
    password = f":{redis.REDIS_PASSWORD}@" if redis.REDIS_PASSWORD else ""
    return f"redis://{password}{redis.REDIS_HOST}:{redis.REDIS_PORT}/{celery.CELERY_REDIS_DB}"


def _build_backend_url() -> str:
    redis = settings.REDIS
    celery = settings.CELERY
    if celery.CELERY_RESULT_BACKEND:
        return celery.CELERY_RESULT_BACKEND
    password = f":{redis.REDIS_PASSWORD}@" if redis.REDIS_PASSWORD else ""
    return f"redis://{password}{redis.REDIS_HOST}:{redis.REDIS_PORT}/{celery.CELERY_REDIS_DB}"


def _load_beat_schedule() -> dict:
    """从 YAML 编排配置加载 Beat 调度（在模块导入时执行，确保 Beat 启动前调度已就绪）。"""
    from pathlib import Path

    import yaml

    from framework.scheduler.cron_utils import parse_cron_to_crontab

    schedule_dir = Path(settings.APP.ROOT_DIR) / "schedules"
    if not schedule_dir.exists():
        return {}

    beat_schedule: dict = {}
    for yml_file in sorted(schedule_dir.glob("*.yml")):
        with open(yml_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        if not config or "name" not in config:
            continue

        pipeline_name = config["name"]
        cron_expr = config.get("cron")
        if cron_expr and config.get("enabled", True):
            try:
                beat_schedule[pipeline_name] = {
                    "task": "worker.orchestration.trigger_pipeline",
                    "schedule": parse_cron_to_crontab(cron_expr),
                    "kwargs": {"pipeline_name": pipeline_name},
                    "options": {"queue": config.get("queue", "celery")},
                }
            except Exception:
                continue
    return beat_schedule


celery_app = Celery("xqtrader")

celery_app.conf.update(
    # Broker & Backend
    broker_url=_build_broker_url(),
    result_backend=_build_backend_url(),

    # 序列化
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # 时区
    timezone="Asia/Shanghai",
    enable_utc=True,

    # 可靠性
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,

    # 结果
    result_expires=3600,

    # Beat
    beat_schedule_filename="celerybeat-schedule",
    beat_max_loop_interval=10,  # Beat 最大检查间隔（秒）
    beat_schedule=_load_beat_schedule(),

    # 任务路由
    task_routes={
        "market.*": {"queue": "market"},
        "factor.*": {"queue": "factor"},
    },
)
