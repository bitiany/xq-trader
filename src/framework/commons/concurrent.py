"""通用并发执行器 — 基于 asyncio.Queue 的生产者-消费者模式。

与 pipeline 模式的区别：
  - pipeline：每个 item 走多阶段 Stage 管线，适合"逐标采集/计算"等固定流程
  - concurrent：每个 item 调一个异步函数，适合"逐因子评估/持久化"等简单场景

设计要点：
  - 生产者协程将 items 流式放入队列，支持动态/惰性生产
  - N 个消费者协程从队列取 items 并独立处理
  - 单 item 失败不影响其他，错误隔离
  - 有界队列实现背压，防止内存暴涨
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")  # item 类型
R = TypeVar("R")  # result 类型


@dataclass
class ConcurrentResult(Generic[R]):
    """生产者-消费者并发执行结果。"""

    succeeded: list[R] = field(default_factory=list)
    failed: list[tuple[Any, Exception]] = field(default_factory=list)
    duration_ms: int = 0

    @property
    def total(self) -> int:
        """总处理数（成功 + 失败）。"""
        return len(self.succeeded) + len(self.failed)

    @property
    def success_count(self) -> int:
        return len(self.succeeded)

    @property
    def failure_count(self) -> int:
        return len(self.failed)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典，用于任务返回值。"""
        return {
            "total": self.total,
            "succeeded": self.success_count,
            "failed": self.failure_count,
            "errors": [
                {"item": str(item), "error": str(exc)}
                for item, exc in self.failed
            ],
            "duration_ms": self.duration_ms,
        }


class ConcurrentRunner(Generic[T, R]):
    """通用生产者-消费者并发执行器。

    基于 asyncio.Queue 实现真正的生产者-消费者模式：
    - 生产者协程将 items 流式放入队列（支持动态/惰性生产）
    - N 个消费者协程从队列取 items 并独立处理
    - 单 item 失败不影响其他，错误隔离
    - 内置进度跟踪和结果汇总

    Args:
        concurrency: 消费者数量（并发数）
        queue_maxsize: 队列最大容量，0=无界（默认），>0 实现背压
        log_name: 日志中的任务名称，用于进度跟踪
    """

    def __init__(
        self,
        concurrency: int = 5,
        queue_maxsize: int = 0,
        log_name: str = "ConcurrentRunner",
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        if queue_maxsize < 0:
            raise ValueError("queue_maxsize must be >= 0")
        self._concurrency = concurrency
        self._queue_maxsize = queue_maxsize
        self._log_name = log_name

    async def run_items(
        self,
        items: list[T],
        processor: Callable[[T], Awaitable[R | None]],
        on_error: Callable[[T, Exception], None] | None = None,
    ) -> ConcurrentResult[R]:
        """简化入口：items 已知，自动构建生产者。

        Args:
            items: 待处理的 item 列表
            processor: 消费者处理函数，接收单个 item，返回结果。
                      返回 None 表示跳过（不计成功也不计失败）。
            on_error: 单 item 处理失败的回调（可选）

        Returns:
            ConcurrentResult: 含 succeeded/failed/duration_ms
        """
        total = len(items)

        async def producer(queue: asyncio.Queue[T | None]) -> None:
            for item in items:
                await queue.put(item)

        return await self._execute(producer, processor, on_error, total=total)

    async def run(
        self,
        producer: Callable[[asyncio.Queue[T]], Awaitable[None]],
        processor: Callable[[T], Awaitable[R | None]],
        on_error: Callable[[T, Exception], None] | None = None,
    ) -> ConcurrentResult[R]:
        """高级入口：自定义生产者，支持动态/惰性/streaming 生产。

        producer 负责将 items put 入队列，不应放入 None（由 runner 处理）。
        processor 返回 None 表示跳过。

        Args:
            producer: 生产者协程函数，接收队列（类型为 asyncio.Queue[T]）
            processor: 消费者处理函数
            on_error: 单 item 处理失败的回调（可选）

        Returns:
            ConcurrentResult
        """
        # 内部队列存储 T | None（None 为退出哨兵），对外暴露为 asyncio.Queue[T]
        async def producer_wrapper(queue: asyncio.Queue[T | None]) -> None:
            typed_queue: asyncio.Queue[T] = queue  # type: ignore[assignment]
            await producer(typed_queue)

        return await self._execute(producer_wrapper, processor, on_error, total=None)

    async def _execute(
        self,
        producer: Callable[[asyncio.Queue[T | None]], Awaitable[None]],
        processor: Callable[[T], Awaitable[R | None]],
        on_error: Callable[[T, Exception], None] | None,
        total: int | None,
    ) -> ConcurrentResult[R]:
        """内部执行入口：启动生产者+消费者，等待完成。"""
        queue: asyncio.Queue[T | None] = asyncio.Queue(maxsize=self._queue_maxsize)
        results: list[R] = []
        errors: list[tuple[Any, Exception]] = []
        completed = 0
        start_time = time.monotonic()
        log_interval = max(1, total // 20) if total else 1

        async def consumer() -> None:
            nonlocal completed
            while True:
                item = await queue.get()
                if item is None:
                    queue.task_done()
                    return  # 退出信号，不计入 completed
                try:
                    try:
                        result = await processor(item)
                        if result is not None:
                            results.append(result)
                    except Exception as e:
                        errors.append((item, e))
                        if on_error:
                            try:
                                on_error(item, e)
                            except Exception:
                                logger.warning(
                                    "[%s] on_error 回调执行失败", self._log_name, exc_info=True,
                                )
                        logger.error(
                            "[%s] item %s 处理失败: %s",
                            self._log_name, item, e, exc_info=True,
                        )
                finally:
                    queue.task_done()
                completed += 1
                if total and (completed % log_interval == 0 or completed == total):
                    self._log_progress(completed, total, start_time, len(errors))

        consumers = [
            asyncio.create_task(consumer(), name=f"{self._log_name}-consumer-{i}")
            for i in range(self._concurrency)
        ]

        producer_task: asyncio.Task[None] = asyncio.create_task(
            producer(queue),  # type: ignore[arg-type]
            name=f"{self._log_name}-producer",
        )
        try:
            await producer_task
        except Exception:
            logger.error("[%s] 生产者异常", self._log_name, exc_info=True)
            for _ in range(self._concurrency):
                await queue.put(None)
            await asyncio.gather(*consumers, return_exceptions=True)
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            return ConcurrentResult(
                succeeded=results, failed=errors, duration_ms=elapsed_ms,
            )

        # 生产者完成，放入 N 个 None 作为消费者退出信号
        for _ in range(self._concurrency):
            await queue.put(None)

        await asyncio.gather(*consumers, return_exceptions=True)

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(
            "[%s] completed: succeeded=%d failed=%d duration=%dms",
            self._log_name, len(results), len(errors), elapsed_ms,
        )
        return ConcurrentResult(
            succeeded=results, failed=errors, duration_ms=elapsed_ms,
        )

    def _log_progress(
        self, completed: int, total: int, start_time: float, error_count: int,
    ) -> None:
        """记录进度日志。"""
        elapsed = time.monotonic() - start_time
        rate = completed / elapsed if elapsed > 0 else 0.0
        eta = (total - completed) / rate if rate > 0 else 0.0
        logger.info(
            "[%s] progress: %d/%d (%.0f%%) failed=%d rate=%.1f/s eta=%.0fs",
            self._log_name, completed, total,
            completed / total * 100, error_count, rate, eta,
        )
