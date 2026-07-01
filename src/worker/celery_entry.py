"""Celery Worker/Beat 启动入口 — 使用 Celery signals 管理初始化生命周期。

初始化流程：
1. worker_init: 启动 AsyncTaskRunner + 初始化数据源 + 建表 + 发现插件 + 调度器
2. beat_init: 初始化数据源 + 建表 + 发现插件 + 注册 Beat 调度
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from celery.signals import beat_init, worker_init, worker_shutdown

from framework.commons.exceptions import PipelineNotFoundError, RecoveryFailedError
from framework.commons.logger import get_logger
from framework.config.settings import settings
from worker.celery_app import celery_app
from worker.executor.async_runner import async_runner
from worker.orchestrator.checkpoint_manager import CheckpointManager
from worker.orchestrator.orchestration_tracker import OrchestrationTracker
from worker.orchestrator.recovery_manager import RecoveryManager
from worker.plugin import autodiscover
from worker.scheduler.barrier_resolver import BarrierResolver
from worker.scheduler.config_sync import ConfigSync
from worker.scheduler.context import set_context
from worker.scheduler.cron_scheduler import CronScheduler
from worker.scheduler.cycle_manager import CycleManager
from worker.scheduler.dag_builder import build_dag
from worker.timeouts import LONG_TASK_TIMEOUT

logger = get_logger("ENTRY")


# ──────────────────────────────────────────────────────────────
# Worker 初始化
# ──────────────────────────────────────────────────────────────


@worker_init.connect
def on_worker_init(**kwargs: object) -> None:
    """Worker 启动时初始化：AsyncTaskRunner + 数据源 + 建表 + 发现插件 + 调度器。"""
    logger.info("Worker 初始化开始...")

    # 1. 启动 AsyncTaskRunner
    async_runner.start()

    # 2. 初始化数据源
    _init_datasource()

    # 3. 初始化管理表
    async_runner.run(_init_tables())

    # 4. 自动发现并注册任务插件
    plugins_dir = str(Path(__file__).parent / "plugins")
    autodiscover(plugins_dir)

    # 5. 注册编排触发任务
    @celery_app.task(
        bind=True,
        name="worker.orchestration.trigger_pipeline",
        max_retries=1,
        time_limit=LONG_TASK_TIMEOUT,
    )
    def trigger_pipeline_task(self: Any, pipeline_name: str) -> dict:
        return _trigger_pipeline(pipeline_name)

    # 6. 注册编排恢复任务
    @celery_app.task(
        bind=True,
        name="worker.orchestration.recover_pipeline",
        max_retries=1,
        time_limit=LONG_TASK_TIMEOUT,
    )
    def recover_pipeline_task(self: Any, orchestration_id: str) -> dict:
        return _recover_pipeline(orchestration_id)

    # 7. 初始化调度器（同步，确保 DAG 上下文在 Worker 就绪前就绑定）
    _init_scheduler()

    logger.info("Worker 初始化完成")


@worker_shutdown.connect
def on_worker_shutdown(**kwargs: object) -> None:
    """Worker 关闭时停止 AsyncTaskRunner。"""
    try:
        async_runner.stop()
    except Exception:
        logger.exception("AsyncTaskRunner 停止失败")
    logger.info("Worker 关闭完成")


# ──────────────────────────────────────────────────────────────
# Beat 初始化
# ──────────────────────────────────────────────────────────────


@beat_init.connect
def on_beat_init(**kwargs: object) -> None:
    """Beat 启动时初始化：数据源 + 建表 + 发现插件 + 注册 Beat 调度。"""
    logger.info("Beat 初始化开始...")

    # 1. 初始化数据源
    _init_datasource()

    # 2. 初始化管理表
    async_runner.start()
    async_runner.run(_init_tables())

    # 3. 自动发现并注册任务插件
    plugins_dir = str(Path(__file__).parent / "plugins")
    autodiscover(plugins_dir)

    logger.info("Beat 初始化完成")


# ──────────────────────────────────────────────────────────────
# 初始化函数
# ──────────────────────────────────────────────────────────────


def _init_datasource() -> None:
    """初始化数据源连接。"""
    from framework.dal.datasource_loader import DatasourceLoader
    from framework.dal.register import register_datasource_sync

    loader = DatasourceLoader(settings.APP.DB_CONFIG_PATH)
    register_datasource_sync(loader.datasources)
    logger.info("数据源初始化完成")


async def _init_tables() -> None:
    """创建 Worker 管理表。"""
    from framework.dal.enginee import engines_manager
    from worker.models import PipelineDef, TaskDef, TaskExec

    for model in [TaskDef, TaskExec, PipelineDef]:
        from sqlalchemy.sql.schema import Table as SaTable

        table: SaTable = model.__table__  # type: ignore[assignment]
        bind_key: str = model.__bind_key__ or "default"
        engine = engines_manager.get_engine(bind_key)
        if engine is None:
            logger.warning("数据源 %s 未注册，跳过建表 %s", bind_key, table.name)
            continue
        async with engine.begin() as conn:
            await conn.run_sync(table.create, checkfirst=True)
        logger.info("管理表 %s 初始化完成", table.name)


def _init_scheduler() -> None:
    """初始化调度器：DAG + 屏障触发器 + 周期管理器 + 编排恢复。"""
    # 1. 从 DB 加载编排配置
    config_sync = ConfigSync({})
    db_config = async_runner.run(config_sync.load_from_db())

    # 2. 加载 YAML 编排配置
    schedule_dir = Path(settings.APP.ROOT_DIR) / "schedules"
    yaml_config = _load_schedules_yaml(str(schedule_dir))

    # 3. 合并配置
    merged_config = ConfigSync.merge_config(yaml_config, db_config)

    # 4. 同步新配置到 DB
    if yaml_config.get("tasks"):
        new_sync = ConfigSync(yaml_config)
        async_runner.run(new_sync.sync_to_db())

    # 5. 构建 DAG
    if not merged_config.get("tasks"):
        logger.info("无编排配置，跳过调度器初始化")
        return

    dag = build_dag(merged_config)

    # 6. 构建 pipeline_steps 映射（pipeline_name → list[step_name]）
    # 只包含步骤节点（type=dependent），排除编排级 cron 节点
    pipeline_steps: dict[str, list[str]] = {}
    for name, node in dag.nodes.items():
        if node.pipeline_name and node.task_type == "dependent":
            pipeline_steps.setdefault(node.pipeline_name, []).append(name)

    # 7. 初始化屏障触发器
    barrier_resolver = BarrierResolver(dag)
    barrier_resolver.write_barrier_configs()

    # 8. 初始化周期管理器
    cycle_manager = CycleManager()

    # 9. 设置全局上下文
    set_context(dag, barrier_resolver, cycle_manager, pipeline_steps)

    # 10. 注册 Beat 调度
    cron_scheduler = CronScheduler(celery_app)
    cron_scheduler.register_cron_tasks(dag)

    # 11. 编排恢复
    checkpoint_manager = CheckpointManager()
    orchestration_tracker = OrchestrationTracker()
    recovery_manager = RecoveryManager(
        checkpoint_manager,
        orchestration_tracker,
    )
    recovered = recovery_manager.scan_and_recover()
    if recovered:
        logger.info("恢复编排: %s", recovered)

    logger.info("调度器初始化完成, DAG 节点数=%d, 编排数=%d", len(dag.nodes), len(pipeline_steps))


def _load_schedules_yaml(schedule_dir: str) -> dict[str, Any]:
    """加载 schedules/ 目录下的 YAML 编排配置，转换为 DAG 配置格式。"""
    import yaml

    schedule_path = Path(schedule_dir)
    if not schedule_path.exists():
        return {"tasks": {}}

    tasks: dict[str, Any] = {}
    for yml_file in sorted(schedule_path.glob("*.yml")):
        with open(yml_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        if not config or "name" not in config or "steps" not in config:
            logger.warning("跳过无效编排配置: %s", yml_file.name)
            continue

        pipeline_name = config["name"]
        steps = config["steps"]
        pipeline_mode = config.get("mode", "barrier")  # barrier（默认）或 canvas

        # 将编排步骤转换为 DAG 节点
        for step in steps:
            step_name = step["name"]
            tasks[step_name] = {
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
        # Beat 触发编排触发器，编排作为整体 Celery 任务执行
        if pipeline_mode == "canvas" and config.get("cron"):
            tasks[pipeline_name] = {
                "type": "cron",
                "mode": "canvas",
                "pipeline_name": pipeline_name,
                "celery_task_name": "worker.orchestration.trigger_pipeline",
                "schedule": config["cron"],
                "kwargs": {"pipeline_name": pipeline_name},
                "queue": config.get("queue", "celery"),
            }

        # 如果编排有 workflow 定义（chain/group/chord），添加编排节点
        if config.get("workflow"):
            tasks[pipeline_name] = {
                "type": "dependent",
                "workflow": config["workflow"],
            }

    return {"tasks": tasks}


def run_worker() -> None:
    """启动 Celery Worker（线程池，4 并发，监听 celery/factor/market 三队列）。"""
    celery_app.worker_main(
        argv=[
            "worker",
            "--loglevel=info",
            "-c",
            "4",
            "-P",
            "threads",
            "-Q",
            "celery,factor,market",
        ]
    )


def run_beat() -> None:
    """启动 Celery Beat。"""
    celery_app.start(argv=["beat", "--loglevel=info"])


def _trigger_pipeline(pipeline_name: str) -> dict:
    """触发编排 — 根据模式选择 barrier（屏障分发）或 canvas（整体执行）。"""
    from worker.scheduler.context import get_cycle_manager, get_dag, get_pipeline_steps

    dag = get_dag()
    cycle_manager = get_cycle_manager()
    pipeline_steps = get_pipeline_steps()
    cycle_id = cycle_manager.current_cycle_id()

    # 找到属于该编排的步骤
    step_names = pipeline_steps.get(pipeline_name, [])
    if not step_names:
        raise PipelineNotFoundError(f"编排 '{pipeline_name}' 未找到或无步骤")

    # 判断编排模式：优先从编排级 DAG 节点获取，否则从步骤节点获取
    pipeline_node = dag.nodes.get(pipeline_name)
    if pipeline_node and pipeline_node.mode:
        pipeline_mode = pipeline_node.mode
    elif step_names:
        pipeline_mode = dag.nodes[step_names[0]].mode
    else:
        pipeline_mode = "barrier"

    # 创建编排记录
    orchestration_id = str(uuid.uuid4())

    tracker = OrchestrationTracker()
    tracker.create(
        orchestration_id=orchestration_id,
        workflow_type=pipeline_mode,
        cycle_id=cycle_id,
        task_name=pipeline_name,
        steps=step_names,
    )

    if pipeline_mode == "canvas":
        # canvas 模式：编排作为整体 Celery 任务，按 DAG 拓扑顺序执行
        return _trigger_canvas_pipeline(
            pipeline_name, orchestration_id, cycle_id, step_names, dag, tracker
        )
    else:
        # barrier 模式（默认）：分发根任务 + 屏障触发器
        return _trigger_barrier_pipeline(
            pipeline_name, orchestration_id, cycle_id, step_names, dag, tracker
        )


def _trigger_barrier_pipeline(
    pipeline_name: str,
    orchestration_id: str,
    cycle_id: str,
    step_names: list[str],
    dag: Any,
    tracker: Any,
) -> dict:
    """屏障模式触发 — 分发根任务，由屏障触发器自动触发下游。"""
    from worker.celery_app import celery_app as app

    # 找到根任务（无依赖的步骤）
    root_tasks = [name for name in step_names if not dag.nodes[name].depends_on]

    triggered = []
    for task_name in root_tasks:
        node = dag.nodes[task_name]
        celery_task_name = node.celery_task_name or task_name
        queue = node.queue or "celery"
        kwargs = dict(node.kwargs or {})
        kwargs["cycle_id"] = cycle_id
        kwargs["orchestration_id"] = orchestration_id
        kwargs["dag_node_name"] = task_name
        kwargs["step_index"] = step_names.index(task_name)
        app.send_task(
            celery_task_name,
            kwargs=kwargs,
            queue=queue,
        )
        triggered.append(celery_task_name)

    # 更新编排状态为 RUNNING
    tracker.update_status(orchestration_id, "RUNNING")

    # 保存 orchestration_id 到 Redis，供屏障触发器传递给下游任务
    from framework.commons.redis_client import redis_client

    redis_client.client.set(f"cycle:{cycle_id}:orchestration_id", orchestration_id, ex=7 * 24 * 3600)  # type: ignore[attr-defined]

    logger.info(
        "触发编排[barrier] %s, orch_id=%s, cycle_id=%s, 根任务=%s",
        pipeline_name, orchestration_id, cycle_id, triggered,
    )
    return {
        "pipeline_name": pipeline_name,
        "orchestration_id": orchestration_id,
        "cycle_id": cycle_id,
        "mode": "barrier",
        "triggered": triggered,
    }


def _trigger_canvas_pipeline(
    pipeline_name: str,
    orchestration_id: str,
    cycle_id: str,
    step_names: list[str],
    dag: Any,
    tracker: Any,
) -> dict:
    """Canvas 模式触发 — 编排作为整体 Celery 任务，按 DAG 拓扑顺序执行。"""
    from worker.celery_app import celery_app as app
    from worker.orchestrator.canvas_builder import CanvasBuilder

    # 构建任务注册表（step_name → Celery Signature），同时注入编排上下文
    task_registry: dict[str, Any] = {}
    # 构建 celery_task_name → step_name 映射
    task_name_map: dict[str, str] = {}
    for idx, step_name in enumerate(step_names):
        node = dag.nodes[step_name]
        celery_task_name = node.celery_task_name or step_name
        task_name_map[celery_task_name] = step_name
        # 注入编排上下文到每个步骤的 kwargs
        step_kwargs = dict(node.kwargs or {})
        step_kwargs["cycle_id"] = cycle_id
        step_kwargs["orchestration_id"] = orchestration_id
        step_kwargs["dag_node_name"] = step_name
        step_kwargs["step_index"] = idx
        task_cls = app.tasks.get(celery_task_name)
        if task_cls is None:
            # 使用 send_task 方式构建 Signature
            task_registry[step_name] = app.signature(celery_task_name, kwargs=step_kwargs)
        else:
            task_registry[step_name] = task_cls.s(**step_kwargs)

    # 按 DAG 拓扑构建 Canvas 工作流
    builder = CanvasBuilder(task_registry)
    canvas_sig = builder.build_from_dag(dag, step_names)

    # 执行 Canvas 工作流
    result = canvas_sig.apply_async()

    # 更新编排状态为 RUNNING
    tracker.update_status(orchestration_id, "RUNNING")

    logger.info(
        "触发编排[canvas] %s, orch_id=%s, cycle_id=%s, canvas_task_id=%s",
        pipeline_name, orchestration_id, cycle_id, result.id,
    )
    return {
        "pipeline_name": pipeline_name,
        "orchestration_id": orchestration_id,
        "cycle_id": cycle_id,
        "mode": "canvas",
        "canvas_task_id": result.id,
    }



def _recover_pipeline(orchestration_id: str) -> dict:
    """恢复失败的编排 — 通过 RecoveryManager 分发恢复点之后的步骤。"""
    checkpoint_manager = CheckpointManager()
    orchestration_tracker = OrchestrationTracker()
    recovery_manager = RecoveryManager(
        checkpoint_manager,
        orchestration_tracker,
    )

    task_id = recovery_manager.recover_orchestration(orchestration_id)
    if task_id is None:
        raise RecoveryFailedError(f"编排 {orchestration_id} 无法恢复（状态不允许或无剩余步骤）")

    logger.info("恢复编排 %s, 新任务ID=%s", orchestration_id, task_id)
    return {"orchestration_id": orchestration_id, "task_id": task_id, "status": "RECOVERING"}
