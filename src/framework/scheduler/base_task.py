"""任务基类 — 插件 SPI 的核心抽象，提供防重入、异步桥接、执行日志、标准化控制台输出。

插件开发者只需继承 BaseTask，定义 task_name + run()。
- run() 返回纯业务数据，框架自动包装为 TaskResult
- 业务异常只需 raise，框架自动处理日志、重试、TaskExec 写入
- 调度配置（cron/queue/timeout 等）在 plugin.yaml 中声明，框架自动合并
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from celery import Task
from celery.exceptions import Ignore

from framework.commons.logger import get_logger
from framework.commons.redis_client import redis_client


@dataclass
class TaskResult:
    """任务执行结果 — 框架自动包装，业务侧无需手动构造。

    业务侧 run() 返回的原始数据会被自动包装为 TaskResult：
    - 成功：TaskResult(success=True, result=原始返回值)
    - 失败：TaskResult(success=False, result=异常信息)
    """

    success: bool = True
    task_name: str = ""
    task_id: str = ""
    result: Any = None
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "task_name": self.task_name,
            "task_id": self.task_id,
            "result": self.result,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
        }


class BaseTask(Task):
    """生产级任务基类 — 插件 SPI 的核心抽象。

    子类必须定义：
    - task_name: str  — 唯一标识，如 "market.daily"
    - run():          — 业务逻辑（支持 async def 或 def）

    run() 返回值：
    - 直接返回业务数据，框架自动包装为 TaskResult
    - 例如 return {"items": [...], "total": 100}
    - 框架会包装为 TaskResult(success=True, result={"items": [...], "total": 100})

    异常处理：
    - 业务侧只需 raise 抛出异常
    - 框架自动捕获 → 记录日志 → 写入 TaskExec → 触发重试

    可选覆盖：
    - description: str
    - time_limit: int
    - max_retries: int
    - prevent_concurrent: bool

    框架自动提供：
    - 防重入（Redis 分布式锁）
    - 异步桥接（async run → 同步 Celery worker）
    - 超时保护
    - 结果自动包装（TaskResult）
    - 执行日志（TaskExec 写入 DB）
    - 标准化控制台日志（执行时间、入参、状态）
    - 调度配置合并（plugin.yaml → 类属性）
    """

    # ── 子类必须定义 ──
    task_name: str = ""
    description: str = ""

    # ── 可覆盖配置（plugin.yaml 可覆盖这些值）──
    time_limit: int = 300
    soft_time_limit: int = 270
    max_retries: int = 3
    prevent_concurrent: bool = True
    autoretry_for: tuple[type[Exception], ...] = (Exception,)  # 异常自动重试

    abstract = True

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if cls.task_name:
            cls.name = cls.task_name

    def run(self, upstream: Any = None, **kwargs: Any) -> Any:
        """业务入口 — 子类覆写。支持 async def 或 def。返回纯业务数据即可。

        upstream: Canvas chain 传递的前一步结果（可选），自动放入 kwargs["upstream"]。
        """
        if upstream is not None:
            kwargs["upstream"] = upstream
        return self._run_impl(**kwargs)

    def _run_impl(self, **kwargs: Any) -> Any:
        """子类覆写此方法实现业务逻辑。"""
        raise NotImplementedError

    # ── 防重入 ──

    def _acquire_lock(self, task_id: str) -> bool:
        """Redis 分布式锁，防止同一任务并发执行。"""
        acquired = redis_client.set(
            f"task_lock:{self.name}", task_id, nx=True, ex=self.time_limit + 60
        )
        return acquired is not None

    def _release_lock(self) -> None:
        """释放分布式锁。"""
        redis_client.delete(f"task_lock:{self.name}")

    # ── 生命周期钩子 ──

    def before_start(self, task_id: str, args: tuple, kwargs: dict) -> None:
        # 重试场景（同 task_id）：锁已在首次执行时获取，跳过锁检查
        is_retry = getattr(self.request, "retries", 0) > 0
        if self.prevent_concurrent and not is_retry and not self._acquire_lock(task_id):
            get_logger("TASK").warning("任务 %s 已在执行，跳过本次触发", self.name)
            raise Ignore()  # type: ignore[misc]

        # 首次执行：记录开始时间；重试：保持首次的 started_at
        if not is_retry:
            self._start_time = time.monotonic()
            self._started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 标准化控制台日志
        retry_info = f" retry={self.request.retries}" if is_retry else ""
        get_logger("TASK").info(
            "[START] task=%s id=%s args=%s%s",
            self.name, task_id, _safe_json(kwargs), retry_info,
        )

        # 首次执行：创建 TaskExec 记录；重试：更新 retry_count
        if not is_retry:
            # 编排任务：设置 parent_id 和 task_type
            orchestration_id = kwargs.get("orchestration_id")
            self._upsert_task_exec(
                task_id=task_id,
                task_name=self.name,
                status="SUCCESS",  # 初始状态，最终由 on_success/on_failure 覆盖
                args=_safe_json(kwargs),
                started_at=self._started_at,
                parent_id=orchestration_id if orchestration_id else None,
                task_type="task" if orchestration_id else None,
            )
        else:
            self._upsert_task_exec(
                task_id=task_id,
                task_name=self.name,
                retry_count=self.request.retries,
            )

    def on_success(self, retval: Any, task_id: str, args: tuple, kwargs: dict) -> None:
        if self.prevent_concurrent:
            self._release_lock()

        duration_ms = int((time.monotonic() - getattr(self, "_start_time", time.monotonic())) * 1000)
        finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 自动包装为 TaskResult
        task_result = TaskResult(
            success=True,
            task_name=self.name,
            task_id=task_id,
            result=retval,
            started_at=getattr(self, "_started_at", ""),
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

        # 标准化控制台日志
        get_logger("TASK").info(
            "[SUCCESS] task=%s id=%s duration=%dms data=%s",
            self.name, task_id, duration_ms, _safe_json(retval),
        )

        # 更新 TaskExec 记录
        self._upsert_task_exec(
            task_id=task_id,
            task_name=self.name,
            status="SUCCESS",
            result=_safe_json(task_result.to_dict()),
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

        # 保存检查点（编排任务）
        self._save_checkpoint(kwargs, "SUCCESS")

        # 通知屏障触发器（编排任务）
        self._notify_barrier(self.name, kwargs, "SUCCESS")

        # Canvas 模式：检查编排是否全部完成
        self._check_canvas_completion(kwargs, "SUCCESS")

    def on_failure(
        self, exc: Exception, task_id: str, args: tuple, kwargs: dict, einfo: Any
    ) -> None:
        if self.prevent_concurrent:
            self._release_lock()

        duration_ms = int((time.monotonic() - getattr(self, "_start_time", time.monotonic())) * 1000)
        finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 自动包装为 TaskResult
        task_result = TaskResult(
            success=False,
            task_name=self.name,
            task_id=task_id,
            result=str(exc),
            started_at=getattr(self, "_started_at", ""),
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

        # 标准化控制台日志
        retry_count = getattr(self.request, "retries", 0)
        get_logger("TASK").error(
            "[FAILURE] task=%s id=%s duration=%dms retry=%d error=%s",
            self.name, task_id, duration_ms, retry_count, exc,
        )

        # 更新 TaskExec 记录
        self._upsert_task_exec(
            task_id=task_id,
            task_name=self.name,
            status="FAILURE",
            result=_safe_json(task_result.to_dict()),
            retry_count=retry_count,
            finished_at=finished_at,
            duration_ms=duration_ms,
        )

        # 保存检查点（编排任务，仅最终失败时保存）
        if retry_count >= self.max_retries:
            self._save_checkpoint(kwargs, "FAILED")

        # 通知屏障触发器（编排任务）
        self._notify_barrier(self.name, kwargs, "FAILED")

        # Canvas 模式：编排失败
        self._check_canvas_completion(kwargs, "FAILED")

    def on_retry(
        self, exc: Exception, task_id: str, args: tuple, kwargs: dict, einfo: Any
    ) -> None:
        retry_count = self.request.retries

        # 标准化控制台日志
        get_logger("TASK").warning(
            "[RETRY] task=%s id=%s retry=%d error=%s",
            self.name, task_id, retry_count, exc,
        )

        # 仅更新 retry_count，不改变 status（status 由最终 on_success/on_failure 决定）
        self._upsert_task_exec(
            task_id=task_id,
            task_name=self.name,
            retry_count=retry_count,
        )

    # ── 编排辅助方法 ──

    def _notify_barrier(self, task_name: str, kwargs: dict, status: str) -> None:
        """通知屏障触发器任务完成（仅编排任务，即 kwargs 含 cycle_id 时）。"""
        cycle_id = kwargs.get("cycle_id")
        if not cycle_id:
            return
        try:
            from worker.scheduler.context import get_barrier_resolver

            barrier = get_barrier_resolver()
            # 优先使用 dag_node_name（由编排触发器注入），避免同名 celery task 的反向映射歧义
            dag_node_name = kwargs.get("dag_node_name", task_name)
            barrier.on_task_completed(dag_node_name, cycle_id, status)
        except RuntimeError:
            # DAG 上下文未初始化（非编排任务），忽略
            pass
        except Exception:
            get_logger("TASK").warning("通知屏障触发器失败: task=%s cycle=%s", task_name, cycle_id, exc_info=True)

    def _save_checkpoint(self, kwargs: dict, status: str) -> None:
        """保存检查点到 Redis（仅编排任务，即 kwargs 含 orchestration_id 和 step_index 时）。"""
        orchestration_id = kwargs.get("orchestration_id")
        step_index = kwargs.get("step_index")
        if not orchestration_id or step_index is None:
            return
        try:
            from worker.orchestrator.checkpoint_manager import CheckpointManager

            checkpoint_manager = CheckpointManager()
            checkpoint_manager.save_checkpoint(orchestration_id, int(step_index), status)
        except Exception:
            get_logger("TASK").warning("保存检查点失败: orch=%s step=%s", orchestration_id, step_index, exc_info=True)

    def _check_canvas_completion(self, kwargs: dict, status: str) -> None:
        """Canvas 模式：检查编排是否全部完成，更新编排状态。"""
        orchestration_id = kwargs.get("orchestration_id")
        step_index = kwargs.get("step_index")
        if not orchestration_id or step_index is None:
            return
        try:
            from worker.orchestrator.checkpoint_manager import CheckpointManager
            from worker.orchestrator.orchestration_tracker import OrchestrationTracker

            checkpoint_manager = CheckpointManager()
            tracker = OrchestrationTracker()

            # 如果当前步骤失败，直接更新编排为 FAILED
            if status == "FAILED":
                tracker.update_status(orchestration_id, "FAILED")
                return

            # 检查所有步骤是否都成功
            checkpoints = checkpoint_manager.read_checkpoint(orchestration_id)
            if not checkpoints:
                return

            # 获取编排的总步骤数
            orch_info = tracker.get(orchestration_id)
            if not orch_info:
                return

            steps_raw = orch_info.get("steps", "[]")
            steps_list = json.loads(steps_raw) if isinstance(steps_raw, str) else steps_raw
            total_steps = len(steps_list)
            success_count = sum(1 for s in checkpoints.values() if s == "SUCCESS")

            if success_count >= total_steps:
                tracker.update_status(orchestration_id, "SUCCESS")
        except Exception:
            get_logger("TASK").warning("检查编排完成状态失败: orch=%s", orchestration_id, exc_info=True)

    def _upsert_task_exec(
        self,
        task_id: str,
        task_name: str,
        task_type: str | None = None,
        status: str | None = None,
        args: str | None = None,
        result: str | None = None,
        retry_count: int | None = None,
        parent_id: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """写入/更新 TaskExec 记录。同一 task_id 重试时更新同一行。"""
        from worker.models import TaskExec

        async def _upsert() -> None:
            data: dict[str, Any] = {}
            if status is not None:
                data["status"] = status
            if args is not None:
                data["args"] = args
            if result is not None:
                data["result"] = result
            if retry_count is not None and retry_count > 0:
                data["retry_count"] = retry_count
            if parent_id is not None:
                data["parent_id"] = parent_id
            if started_at is not None:
                data["started_at"] = started_at
            if finished_at is not None:
                data["finished_at"] = finished_at
            if duration_ms is not None:
                data["duration_ms"] = duration_ms

            existing = await TaskExec.get_one_or_none(id=task_id)
            if existing:
                # 更新已有记录（重试场景）
                if data:
                    await existing.update(data)
            else:
                # 创建新记录
                data["id"] = task_id
                data["task_name"] = task_name
                if task_type is not None:
                    data["task_type"] = task_type
                if parent_id is not None:
                    data["parent_id"] = parent_id
                await TaskExec.create(**data)

        try:
            # 使用 AsyncTaskRunner 持久化事件循环，避免 asyncio.run() 导致 asyncpg 连接池失效
            from worker.executor.async_runner import async_runner

            if async_runner._loop is not None and async_runner._loop.is_running():
                async_runner.run(_upsert())
            else:
                # Worker 未启动时（如测试），使用独立事件循环
                asyncio.run(_upsert())
        except Exception:
            get_logger("TASK").warning("写入 TaskExec 失败: %s", task_id, exc_info=True)


def apply_yaml_config(task_cls: type[BaseTask], manifest: Any) -> type[BaseTask]:
    """将 plugin.yaml 中的配置合并到 BaseTask 子类属性上。"""
    task_cls.time_limit = manifest.timeout
    task_cls.soft_time_limit = max(manifest.timeout - 30, 60)
    task_cls.max_retries = manifest.retry_config.get("max_retries", 3)
    # Celery Task 类属性
    setattr(task_cls, "retry_backoff", manifest.retry_config.get("retry_backoff", True))
    setattr(task_cls, "retry_backoff_max", manifest.retry_config.get("retry_backoff_max", 600))
    task_cls.acks_late = True
    task_cls.reject_on_worker_lost = True
    return task_cls


def ensure_async_run(task_cls: type[BaseTask]) -> type[BaseTask]:
    """确保 _run_impl() 方法支持异步桥接 — 若 _run_impl 是 async，自动包装为同步调用。

    优先使用 AsyncTaskRunner 的事件循环（复用 asyncpg 连接池），
    仅在 Worker 未启动时回退到 asyncio.new_event_loop()。
    """
    original_run_impl = task_cls._run_impl

    if asyncio.iscoroutinefunction(original_run_impl):
        def sync_run_impl(self: BaseTask, **kwargs: Any) -> Any:
            from worker.executor.async_runner import async_runner

            if async_runner._loop is not None and async_runner._loop.is_running():
                return async_runner.run(
                    original_run_impl(self, **kwargs),
                    timeout=self.time_limit,
                )

            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(original_run_impl(self, **kwargs))
            finally:
                loop.close()

        task_cls._run_impl = sync_run_impl  # type: ignore[assignment]

    return task_cls


# ──────────────────────────────────────────────────────────────
# 任务执行日志 — 写入 TaskExec 表
# ──────────────────────────────────────────────────────────────


def _safe_json(obj: Any) -> str:
    """安全序列化为 JSON 字符串，失败则返回 str()。"""
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(obj)
