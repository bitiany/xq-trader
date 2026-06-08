"""异步任务运行器 — 维护持久化事件循环线程，确保 asyncpg 连接池始终在同一个循环中。"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

from framework.commons.exceptions import WorkerNotInitializedError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AsyncTaskRunner:
    """Celery Worker 中异步任务运行器。

    维护一个持久化的事件循环线程，确保 asyncpg 连接池
    始终在同一个事件循环中创建和使用，避免 asyncio.run()
    每次创建新循环导致连接池失效的问题。
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()

    def start(self) -> None:
        if self._loop is not None:
            return
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="async-runner"
        )
        self._thread.start()
        self._started.wait(timeout=30)
        logger.info("AsyncTaskRunner started")

    def stop(self) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=10)
        self._loop = None
        self._thread = None
        logger.info("AsyncTaskRunner stopped")

    def run(self, coro: Coroutine[Any, Any, T], timeout: float | None = None) -> T:
        if self._loop is None or not self._loop.is_running():
            raise WorkerNotInitializedError("AsyncTaskRunner is not started")
        effective_timeout = timeout if timeout is not None else 600
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=effective_timeout)
        except TimeoutError:
            future.cancel()
            logger.error(
                "AsyncTaskRunner coroutine timed out after %ss, cancelled",
                effective_timeout,
            )
            raise

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            raise WorkerNotInitializedError("AsyncTaskRunner is not started")
        return self._loop

    @property
    def is_running(self) -> bool:
        """检查 AsyncTaskRunner 是否已启动且事件循环正在运行。"""
        return self._loop is not None and self._loop.is_running()

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._started.set()
        self._loop.run_forever()


async_runner = AsyncTaskRunner()
