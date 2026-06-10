"""通用限流器 — 支持滑动窗口和令牌桶两种模式。

滑动窗口限流器（SlidingWindowLimiter）：
  适用于 tushare 等按"每分钟N次"限制的 API。
  记录每次请求的时间戳，在滑动窗口内请求数不超过限制。

令牌桶限流器（TokenBucketLimiter）：
  适用于允许短时突发的场景。
  令牌以固定速率填充，每次请求消耗一个令牌，桶满时停止填充，桶空时等待。

两者均使用 threading.Lock 保证线程安全，适用于 asyncio + to_thread 混合场景。
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque

from framework.commons.logger import get_logger

logger = get_logger(__name__)


class SlidingWindowLimiter:
    """线程安全的滑动窗口限流器。

    在任意时间窗口 [now - window_seconds, now] 内，请求数不超过 max_requests。
    适用于 tushare 等"每分钟500次"的滚动窗口限流场景。

    线程安全：
      使用 threading.Lock 保护请求时间戳队列，确保在以下场景均正确限流：
      - 多个 asyncio 协程并发 acquire()
      - asyncio.to_thread 将同步调用放入线程池后，多个线程同时执行
      - 多线程直接调用 acquire_sync()
    """

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        if max_requests <= 0:
            raise ValueError(f"max_requests 必须大于 0，当前值: {max_requests}")
        if window_seconds <= 0:
            raise ValueError(f"window_seconds 必须大于 0，当前值: {window_seconds}")

        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    @property
    def max_requests(self) -> int:
        return self._max_requests

    @property
    def window_seconds(self) -> float:
        return self._window_seconds

    def _purge(self) -> None:
        """移除窗口外的时间戳（需在锁内调用）。"""
        cutoff = time.monotonic() - self._window_seconds
        while self._timestamps and self._timestamps[0] <= cutoff:
            self._timestamps.popleft()

    def _try_acquire(self) -> tuple[bool, float]:
        """尝试获取许可（需在锁内调用）。

        Returns:
            (success, wait_time) — success=True 表示获取成功；
            success=False 表示需等待 wait_time 秒后重试。
        """
        self._purge()
        if len(self._timestamps) < self._max_requests:
            self._timestamps.append(time.monotonic())
            return True, 0.0
        # 窗口已满，计算最早请求过期时间
        wait_time = self._timestamps[0] - (time.monotonic() - self._window_seconds)
        return False, max(0.0, wait_time)

    async def acquire(self) -> None:
        """异步获取许可，窗口满时阻塞等待。

        适用于 asyncio 协程场景。在锁外 await asyncio.sleep() 等待，
        不阻塞事件循环。
        """
        while True:
            with self._lock:
                success, wait_time = self._try_acquire()
                if success:
                    return

            logger.debug(
                "滑动窗口等待: wait=%.2fs window=%.0fs max=%d current=%d",
                wait_time, self._window_seconds, self._max_requests, len(self._timestamps),
            )
            await asyncio.sleep(wait_time + 0.01)  # 加微小缓冲避免边界竞争

    def acquire_sync(self) -> None:
        """同步获取许可，窗口满时阻塞等待。

        适用于多线程场景。
        """
        while True:
            with self._lock:
                success, wait_time = self._try_acquire()
                if success:
                    return

            logger.debug(
                "滑动窗口等待(sync): wait=%.2fs window=%.0fs max=%d current=%d",
                wait_time, self._window_seconds, self._max_requests, len(self._timestamps),
            )
            time.sleep(wait_time + 0.01)

    async def try_acquire(self) -> bool:
        """尝试获取许可，不阻塞。"""
        with self._lock:
            success, _ = self._try_acquire()
            return success


class TokenBucketLimiter:
    """线程安全的令牌桶限流器。

    令牌桶算法核心参数：
      - capacity: 桶容量（最大令牌数），允许短时突发
      - refill_rate: 令牌填充速率（每秒填充令牌数）

    工作流程：
      1. 桶初始满载（capacity 个令牌）
      2. 每次请求调用 acquire() 消耗 1 个令牌
      3. 后台按 refill_rate 持续填充令牌，不超过 capacity
      4. 桶空时 acquire() 阻塞等待直到有令牌可用

    线程安全：
      使用 threading.Lock 保护令牌状态，确保在以下场景均正确限流：
      - 多个 asyncio 协程并发 acquire()
      - asyncio.to_thread 将同步调用放入线程池后，多个线程同时执行
      - 多线程直接调用 acquire_sync()
    """

    def __init__(self, capacity: int, refill_rate: float) -> None:
        if capacity <= 0:
            raise ValueError(f"capacity 必须大于 0，当前值: {capacity}")
        if refill_rate <= 0:
            raise ValueError(f"refill_rate 必须大于 0，当前值: {refill_rate}")

        self._capacity = capacity
        self._refill_rate = refill_rate
        self._tokens: float = float(capacity)
        self._last_refill: float = time.monotonic()
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def refill_rate(self) -> float:
        return self._refill_rate

    @property
    def available_tokens(self) -> float:
        """当前可用令牌数（近似值，不加锁）。"""
        return self._tokens

    def _refill(self) -> None:
        """根据经过时间填充令牌（需在锁内调用）。"""
        now = time.monotonic()
        elapsed = now - self._last_refill
        added = elapsed * self._refill_rate
        if added > 0:
            self._tokens = min(self._capacity, self._tokens + added)
            self._last_refill = now

    def _try_consume(self, tokens: int) -> tuple[bool, float]:
        """尝试消耗令牌（需在锁内调用）。

        Returns:
            (success, deficit) — success=True 表示消耗成功，deficit=0；
            success=False 表示令牌不足，deficit 为缺口数量。
        """
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True, 0.0
        return False, tokens - self._tokens

    async def acquire(self, tokens: int = 1) -> None:
        """异步获取令牌，桶空时阻塞等待。

        适用于 asyncio 协程场景。在锁外 await asyncio.sleep() 等待，
        不阻塞事件循环。

        Args:
            tokens: 本次请求消耗的令牌数，默认 1
        """
        if tokens > self._capacity:
            logger.warning(
                "请求令牌数 %d 超过桶容量 %d，将等待足够令牌",
                tokens, self._capacity,
            )

        while True:
            with self._lock:
                success, deficit = self._try_consume(tokens)
                if success:
                    return

            wait_time = deficit / self._refill_rate
            logger.debug(
                "令牌桶等待: deficit=%.1f wait=%.2fs available=%.1f",
                deficit, wait_time, self._tokens,
            )
            await asyncio.sleep(wait_time)

    def acquire_sync(self, tokens: int = 1) -> None:
        """同步获取令牌，桶空时阻塞等待。

        适用于多线程场景。

        Args:
            tokens: 本次请求消耗的令牌数，默认 1
        """
        if tokens > self._capacity:
            logger.warning(
                "请求令牌数 %d 超过桶容量 %d，将等待足够令牌",
                tokens, self._capacity,
            )

        while True:
            with self._lock:
                success, deficit = self._try_consume(tokens)
                if success:
                    return

            wait_time = deficit / self._refill_rate
            logger.debug(
                "令牌桶等待(sync): deficit=%.1f wait=%.2fs available=%.1f",
                deficit, wait_time, self._tokens,
            )
            time.sleep(wait_time)

    async def try_acquire(self, tokens: int = 1) -> bool:
        """尝试获取令牌，不阻塞。"""
        with self._lock:
            success, _ = self._try_consume(tokens)
            return success
