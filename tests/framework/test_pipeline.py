"""管道引擎单元测试 — 验证核心框架的并发执行、切面、上下文传递。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from framework.pipeline import (
    Aspect,
    Pipeline,
    PipelineContext,
    PipelineEngine,
    Stage,
    StageResult,
)
from framework.pipeline.errors import PipelineAspectError, PipelineStageError
from framework.pipeline.models import StageResult as SR


# ==================== 测试用 Stage ====================


class DoubleStage(Stage):
    """将 item 数值翻倍。"""

    @property
    def name(self) -> str:
        return "double"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        result = item * 2
        ctx.set("doubled", result)
        return StageResult.ok(data=result)


class AddStage(Stage):
    """将 item 加上上下文中的 offset。"""

    @property
    def name(self) -> str:
        return "add"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        offset = ctx.get("offset", 0)
        result = item + offset
        ctx.set("added", result)
        return StageResult.ok(data=result)


class FailStage(Stage):
    """始终失败的 Stage。"""

    @property
    def name(self) -> str:
        return "fail"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        return StageResult.fail(f"intentional failure for {item}")


class ErrorStage(Stage):
    """抛出异常的 Stage。"""

    @property
    def name(self) -> str:
        return "error"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        raise ValueError(f"boom for {item}")


# ==================== 测试用 Aspect ====================


class TrackingAspect(Aspect):
    """追踪 before/after/on_error 调用。"""

    def __init__(self) -> None:
        self.before_calls: list[Any] = []
        self.after_calls: list[Any] = []
        self.error_calls: list[Any] = []

    @property
    def name(self) -> str:
        return "tracking"

    async def before(self, item: Any, ctx: PipelineContext) -> None:
        self.before_calls.append(item)
        ctx.set("offset", 10)

    async def after(self, item: Any, ctx: PipelineContext, result: StageResult) -> None:
        self.after_calls.append(item)

    async def on_error(self, item: Any, ctx: PipelineContext, error: Exception) -> None:
        self.error_calls.append(item)


# ==================== 测试 ====================


class TestStageResult:
    """StageResult 测试。"""

    def test_ok(self) -> None:
        r = StageResult.ok(data=42)
        assert r.success is True
        assert r.data == 42
        assert r.error is None

    def test_fail(self) -> None:
        r = StageResult.fail("something went wrong")
        assert r.success is False
        assert r.data is None
        assert r.error == "something went wrong"


class TestPipelineContext:
    """PipelineContext 测试。"""

    def test_get_set(self) -> None:
        ctx = PipelineContext(pipeline_name="test", item="000001.SZ")
        ctx.set("key", "value")
        assert ctx.get("key") == "value"
        assert ctx.get("missing") is None
        assert ctx.get("missing", 42) == 42

    def test_update(self) -> None:
        ctx = PipelineContext(pipeline_name="test", item="item1")
        ctx.update({"a": 1, "b": 2})
        assert ctx.get("a") == 1
        assert ctx.get("b") == 2

    def test_contains(self) -> None:
        ctx = PipelineContext(pipeline_name="test", item="item1")
        ctx.set("key", "value")
        assert ctx.contains("key") is True
        assert ctx.contains("missing") is False

    def test_to_dict(self) -> None:
        ctx = PipelineContext(pipeline_name="test", item="item1")
        ctx.set("watermark_date", "2024-01-01")
        d = ctx.to_dict()
        assert d["pipeline_name"] == "test"
        assert d["item"] == "item1"
        assert d["watermark_date"] == "2024-01-01"


class TestPipelineEngine:
    """管道引擎核心功能测试 — 使用 asyncio.run() 避免与 conftest event_loop 冲突。"""

    def test_basic_pipeline(self) -> None:
        result = asyncio.run(self._run_basic())
        assert result.total == 3
        assert result.succeeded == 3
        assert result.failed == 0
        assert result.pipeline_name == "test"

    async def _run_basic(self) -> Any:
        pipeline = Pipeline(name="test", stages=[DoubleStage(), AddStage()])
        engine = PipelineEngine(pipelines=[pipeline], concurrency=2, queue_size=10)
        return await engine.execute([1, 2, 3])

    def test_pipeline_with_aspect(self) -> None:
        aspect = TrackingAspect()
        result = asyncio.run(self._run_with_aspect(aspect))
        assert result.succeeded == 2
        assert sorted(aspect.before_calls) == [1, 2]
        assert sorted(aspect.after_calls) == [1, 2]
        assert aspect.error_calls == []

    async def _run_with_aspect(self, aspect: TrackingAspect) -> Any:
        pipeline = Pipeline(
            name="test_aspect", stages=[DoubleStage(), AddStage()], aspects=[aspect],
        )
        engine = PipelineEngine(pipelines=[pipeline], concurrency=2, queue_size=10)
        return await engine.execute([1, 2])

    def test_pipeline_stage_failure(self) -> None:
        result = asyncio.run(self._run_stage_failure())
        assert result.total == 2
        assert result.skipped == 2
        assert result.succeeded == 0

    async def _run_stage_failure(self) -> Any:
        pipeline = Pipeline(name="test_fail", stages=[FailStage(), DoubleStage()])
        engine = PipelineEngine(pipelines=[pipeline], concurrency=2, queue_size=10)
        return await engine.execute([1, 2])

    def test_pipeline_stage_error(self) -> None:
        aspect = TrackingAspect()
        result = asyncio.run(self._run_stage_error(aspect))
        assert result.total == 3
        assert result.failed == 3
        assert result.succeeded == 0
        assert len(aspect.error_calls) == 3

    async def _run_stage_error(self, aspect: TrackingAspect) -> Any:
        pipeline = Pipeline(name="test_error", stages=[ErrorStage()], aspects=[aspect])
        engine = PipelineEngine(pipelines=[pipeline], concurrency=2, queue_size=10)
        return await engine.execute([1, 2, 3])

    def test_pipeline_concurrency(self) -> None:
        result = asyncio.run(self._run_concurrency())
        assert result.total == 20
        assert result.succeeded == 20
        assert result.failed == 0

    async def _run_concurrency(self) -> Any:
        pipeline = Pipeline(name="test_concurrent", stages=[DoubleStage()])
        engine = PipelineEngine(pipelines=[pipeline], concurrency=5, queue_size=50)
        return await engine.execute(list(range(20)))

    def test_pipeline_empty_items(self) -> None:
        result = asyncio.run(self._run_empty())
        assert result.total == 0
        assert result.succeeded == 0
        assert result.failed == 0

    async def _run_empty(self) -> Any:
        pipeline = Pipeline(name="test_empty", stages=[DoubleStage()])
        engine = PipelineEngine(pipelines=[pipeline], concurrency=2, queue_size=10)
        return await engine.execute([])

    def test_pipeline_result_to_dict(self) -> None:
        result = asyncio.run(self._run_to_dict())
        d = result.to_dict()
        assert d["pipeline_name"] == "test_dict"
        assert d["total"] == 1
        assert d["succeeded"] == 1
        assert "errors" in d

    async def _run_to_dict(self) -> Any:
        pipeline = Pipeline(name="test_dict", stages=[DoubleStage()])
        engine = PipelineEngine(pipelines=[pipeline], concurrency=1, queue_size=10)
        return await engine.execute([1])
