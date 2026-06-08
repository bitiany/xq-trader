"""通用令牌桶限流器。

基于令牌桶算法实现异步限流，适用于外部 API 调用频率控制。
令牌以固定速率填充，每次请求消耗一个令牌，桶满时停止填充，桶空时等待。
"""

from __future__ import annotations

import asyncio
import time

from framework.commons.logger import get_logger

logger = get_logger(__name__)


class TokenBucketLimiter:
    """异步令牌桶限流器。

    令牌桶算法核心参数：
      - capacity: 桶容量（最大令牌数），允许短时突发
      - refill_rate: 令牌填充速率（每秒填充令牌数）

    工作流程：
      1. 桶初始满载（capacity 个令牌）
      2. 每次请求调用 acquire() 消耗 1 个令牌
      3. 后台按 refill_rate 持续填充令牌，不超过 capacity
      4. 桶空时 acquire() 阻塞等待直到有令牌可用

    示例：tushare 限流 500次/分钟 → capacity=500, refill_rate=500/60≈8.33
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
        self._lock = asyncio.Lock()

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
        """根据经过时间填充令牌。"""
        now = time.monotonic()
        elapsed = now - self._last_refill
        added = elapsed * self._refill_rate
        if added > 0:
            self._tokens = min(self._capacity, self._tokens + added)
            self._last_refill = now

    async def acquire(self, tokens: int = 1) -> None:
        """获取令牌，桶空时阻塞等待。

        Args:
            tokens: 本次请求消耗的令牌数，默认 1
        """
        if tokens > self._capacity:
            logger.warning(
                "请求令牌数 %d 超过桶容量 %d，将等待足够令牌",
                tokens, self._capacity,
            )

        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens

            # 等待令牌填充到足够数量
            wait_time = deficit / self._refill_rate
            logger.debug(
                "令牌桶等待: deficit=%.1f wait=%.2fs available=%.1f",
                deficit, wait_time, self._tokens,
            )
            await asyncio.sleep(wait_time)

    async def try_acquire(self, tokens: int = 1) -> bool:
        """尝试获取令牌，不阻塞。

        Returns:
            True 表示获取成功，False 表示令牌不足
        """
        async with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False
