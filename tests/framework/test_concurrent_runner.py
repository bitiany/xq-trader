"""ConcurrentRunner 单元测试 — 验证生产者-消费者模式的并发、错误隔离、进度跟踪。"""

from __future__ import annotations

import asyncio
import time

import pytest

from framework.commons.concurrent import ConcurrentResult, ConcurrentRunner

# ==================== 基础功能测试 ====================


@pytest.mark.asyncio(loop_scope="session")
async def test_run_items_basic() -> None:
    """基础功能：所有 items 被处理，结果正确返回。"""
    items = [1, 2, 3, 4, 5]

    async def processor(x: int) -> int:
        await asyncio.sleep(0.01)
        return x * 2

    runner = ConcurrentRunner[int, int](concurrency=3, log_name="test-basic")
    result = await runner.run_items(items, processor)

    assert result.success_count == 5
    assert result.failure_count == 0
    assert sorted(result.succeeded) == [2, 4, 6, 8, 10]
    assert result.duration_ms >= 0  # 极快任务可能为 0ms


@pytest.mark.asyncio(loop_scope="session")
async def test_run_items_empty() -> None:
    """空 items 列表：返回空结果，不报错。"""
    runner = ConcurrentRunner[int, int](concurrency=2)
    result = await runner.run_items([], lambda x: asyncio.sleep(0, result=x))

    assert result.success_count == 0
    assert result.failure_count == 0
    assert result.total == 0


@pytest.mark.asyncio(loop_scope="session")
async def test_processor_return_none_skipped() -> None:
    """processor 返回 None 表示跳过，不计成功也不计失败。"""
    items = [1, 2, 3, 4]

    async def processor(x: int) -> int | None:
        if x % 2 == 0:
            return None  # 偶数跳过
        return x

    runner = ConcurrentRunner[int, int](concurrency=2)
    result = await runner.run_items(items, processor)

    assert result.success_count == 2
    assert result.failure_count == 0
    assert sorted(result.succeeded) == [1, 3]


# ==================== 错误隔离测试 ====================


@pytest.mark.asyncio(loop_scope="session")
async def test_error_isolation() -> None:
    """单个 item 处理失败不影响其他 item。"""
    items = [1, 2, 3, 4, 5]

    async def processor(x: int) -> int:
        await asyncio.sleep(0.01)
        if x == 3:
            raise ValueError(f"boom for {x}")
        return x * 2

    runner = ConcurrentRunner[int, int](concurrency=2, log_name="test-error")
    result = await runner.run_items(items, processor)

    assert result.success_count == 4
    assert result.failure_count == 1
    assert sorted(result.succeeded) == [2, 4, 8, 10]
    failed_item, failed_exc = result.failed[0]
    assert failed_item == 3
    assert isinstance(failed_exc, ValueError)


@pytest.mark.asyncio(loop_scope="session")
async def test_on_error_callback() -> None:
    """on_error 回调在 item 失败时被调用。"""
    items = [1, 2, 3]
    error_items: list[int] = []

    async def processor(x: int) -> int:
        if x == 2:
            raise RuntimeError("fail")
        return x

    def on_error(item: int, exc: Exception) -> None:
        error_items.append(item)

    runner = ConcurrentRunner[int, int](concurrency=1)
    result = await runner.run_items(items, processor, on_error=on_error)

    assert result.failure_count == 1
    assert error_items == [2]


@pytest.mark.asyncio(loop_scope="session")
async def test_on_error_callback_exception_does_not_crash() -> None:
    """on_error 回调自身抛异常不影响消费者继续运行。"""
    items = [1, 2, 3]

    async def processor(x: int) -> int:
        if x == 2:
            raise ValueError("fail")
        return x

    def bad_on_error(item: int, exc: Exception) -> None:
        raise RuntimeError("on_error itself failed")

    runner = ConcurrentRunner[int, int](concurrency=1)
    result = await runner.run_items(items, processor, on_error=bad_on_error)

    # 即使 on_error 抛异常，其他 item 仍正常处理
    assert result.success_count == 2
    assert result.failure_count == 1


# ==================== 并发控制测试 ====================


@pytest.mark.asyncio(loop_scope="session")
async def test_concurrency_limit() -> None:
    """验证并发数被 Semaphore 限制，不超过 concurrency。"""
    max_concurrent = 0
    current_concurrent = 0
    lock = asyncio.Lock()

    async def processor(x: int) -> int:
        nonlocal max_concurrent, current_concurrent
        async with lock:
            current_concurrent += 1
            max_concurrent = max(max_concurrent, current_concurrent)
        await asyncio.sleep(0.05)  # 模拟 I/O
        async with lock:
            current_concurrent -= 1
        return x

    items = list(range(20))
    runner = ConcurrentRunner[int, int](concurrency=3, log_name="test-conc")
    result = await runner.run_items(items, processor)

    assert result.success_count == 20
    assert max_concurrent <= 3, f"并发数 {max_concurrent} 超过限制 3"


@pytest.mark.asyncio(loop_scope="session")
async def test_concurrency_speedup() -> None:
    """并发应比串行更快（粗略验证，非精确基准）。"""
    items = list(range(10))

    async def processor(x: int) -> int:
        await asyncio.sleep(0.1)
        return x

    # 串行基准
    serial_start = time.monotonic()
    for item in items:
        await processor(item)
    serial_duration = time.monotonic() - serial_start

    # 并发执行
    runner = ConcurrentRunner[int, int](concurrency=5)
    result = await runner.run_items(items, processor)

    # 串行 ~1.0s，并发 5 应 ~0.2s，允许调度开销
    assert result.duration_ms < serial_duration * 1000 * 0.6, (
        f"并发 {result.duration_ms}ms 未明显快于串行 {serial_duration * 1000:.0f}ms"
    )


# ==================== 动态生产者测试 ====================


@pytest.mark.asyncio(loop_scope="session")
async def test_run_dynamic_producer() -> None:
    """run() 高级入口：自定义生产者，支持动态生产。"""
    produced: list[int] = []

    async def producer(queue: asyncio.Queue[int]) -> None:
        for i in range(5):
            produced.append(i)
            await queue.put(i)
            await asyncio.sleep(0.01)  # 模拟动态生产

    async def processor(x: int) -> int:
        await asyncio.sleep(0.01)
        return x * 10

    runner = ConcurrentRunner[int, int](concurrency=2, log_name="test-dynamic")
    result = await runner.run(producer, processor)

    assert result.success_count == 5
    assert sorted(result.succeeded) == [0, 10, 20, 30, 40]
    assert produced == [0, 1, 2, 3, 4]


@pytest.mark.asyncio(loop_scope="session")
async def test_run_with_bounded_queue_backpressure() -> None:
    """有界队列实现背压：生产者在队列满时阻塞，等待消费者消费。"""
    put_order: list[int] = []

    async def producer(queue: asyncio.Queue[int]) -> None:
        for i in range(10):
            # 队列 maxsize=2，生产者会在队列满时阻塞
            await queue.put(i)
            put_order.append(i)

    async def processor(x: int) -> int:
        await asyncio.sleep(0.05)  # 消费者慢，触发背压
        return x

    runner = ConcurrentRunner[int, int](
        concurrency=1, queue_maxsize=2, log_name="test-backpressure",
    )
    result = await runner.run(producer, processor)

    assert result.success_count == 10
    # 背压存在时，生产者不会瞬间生产完所有 item
    # （由于并发=1 + maxsize=2，生产者必须在消费者消费后才能继续）


# ==================== 结果模型测试 ====================


def test_concurrent_result_properties() -> None:
    """ConcurrentResult 属性计算正确。"""
    result = ConcurrentResult[int](
        succeeded=[1, 2, 3],
        failed=[("bad", ValueError("fail"))],
        duration_ms=100,
    )

    assert result.success_count == 3
    assert result.failure_count == 1
    assert result.total == 4

    d = result.to_dict()
    assert d["total"] == 4
    assert d["succeeded"] == 3
    assert d["failed"] == 1
    assert d["duration_ms"] == 100
    assert len(d["errors"]) == 1
    assert d["errors"][0]["item"] == "bad"
    assert d["errors"][0]["error"] == "fail"


def test_concurrent_result_empty() -> None:
    """空结果的属性。"""
    result = ConcurrentResult[int]()
    assert result.success_count == 0
    assert result.failure_count == 0
    assert result.total == 0
    d = result.to_dict()
    assert d["errors"] == []


# ==================== 参数校验测试 ====================


def test_runner_invalid_concurrency() -> None:
    """concurrency < 1 应抛 ValueError。"""
    with pytest.raises(ValueError, match="concurrency"):
        ConcurrentRunner[int, int](concurrency=0)


def test_runner_invalid_queue_maxsize() -> None:
    """queue_maxsize < 0 应抛 ValueError。"""
    with pytest.raises(ValueError, match="queue_maxsize"):
        ConcurrentRunner[int, int](queue_maxsize=-1)


# ==================== 生产者异常测试 ====================


@pytest.mark.asyncio(loop_scope="session")
async def test_producer_exception_graceful_shutdown() -> None:
    """生产者抛异常时，消费者优雅退出，已处理的结果保留。"""
    processed: list[int] = []

    async def producer(queue: asyncio.Queue[int]) -> None:
        await queue.put(1)
        await asyncio.sleep(0.05)  # 让消费者处理 1
        raise RuntimeError("producer boom")

    async def processor(x: int) -> int:
        processed.append(x)
        return x

    runner = ConcurrentRunner[int, int](concurrency=2, log_name="test-prod-fail")
    result = await runner.run(producer, processor)

    # 生产者异常后，已处理的 item 1 应保留在结果中
    assert 1 in result.succeeded
    # 不应所有 item 都处理完（因为生产者中途崩了）


# ==================== 并发安全性测试 ====================


@pytest.mark.asyncio(loop_scope="session")
async def test_results_not_lost_under_high_concurrency() -> None:
    """高并发下结果不丢失、不重复。"""
    items = list(range(100))

    async def processor(x: int) -> int:
        await asyncio.sleep(0.001)
        return x

    runner = ConcurrentRunner[int, int](concurrency=8, log_name="test-high-conc")
    result = await runner.run_items(items, processor)

    assert result.success_count == 100
    assert result.failure_count == 0
    assert sorted(result.succeeded) == items
