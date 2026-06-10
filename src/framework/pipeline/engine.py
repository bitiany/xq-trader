"""管道引擎 — 并发管线执行器。

架构：
  Producer → Semaphore 控制并发 → 每条数据走 Pipeline(stages + aspects)

  - Semaphore 控制最大并发数
  - 每条数据独立走完所有 Stage，item 之间互不依赖
  - 每个 Pipeline 支持前切/后切（Aspect）
  - 每个 Pipeline 拥有独立上下文（PipelineContext）
  - 单条失败不影响其他，错误汇总到 PipelineResult
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable
from typing import Any

from framework.pipeline.context import PipelineContext
from framework.pipeline.errors import PipelineAspectError, PipelineError, PipelineStageError
from framework.pipeline.models import ItemError, PipelineResult, StageResult
from framework.pipeline.stage import Aspect, Stage

logger = logging.getLogger(__name__)


class Pipeline:
    """管线定义 — 一组串行 Stage + 切面 Aspect。"""

    def __init__(
        self,
        name: str,
        stages: list[Stage],
        aspects: list[Aspect] | None = None,
    ) -> None:
        self.name = name
        self.stages = stages
        self.aspects = aspects or []

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        """对单条数据执行完整管线：前切 → stages → 后切。

        Args:
            item: 待处理的数据
            ctx: 管线上下文

        Returns:
            最后一个 Stage 的执行结果
        """
        result = StageResult.ok()

        # 前切
        for aspect in self.aspects:
            try:
                await aspect.before(item, ctx)
            except Exception as e:
                raise PipelineAspectError(aspect.name, "before", item, str(e)) from e

        # 串行执行 Stage
        for stage in self.stages:
            try:
                result = await stage.process(item, ctx)
                if not result.success:
                    logger.warning(
                        "Stage [%s] returned failure for item %s: %s",
                        stage.name, item, result.error,
                    )
                    break
            except Exception as e:
                raise PipelineStageError(stage.name, item, str(e)) from e

        # 后切
        for aspect in reversed(self.aspects):
            try:
                await aspect.after(item, ctx, result)
            except Exception as e:
                raise PipelineAspectError(aspect.name, "after", item, str(e)) from e

        return result


class PipelineEngine:
    """管道引擎 — 并发管线执行器。

    使用 asyncio.Semaphore 控制并发数：
      1. 将 items 拆分为多个并发任务
      2. Semaphore 限制同时执行的任务数
      3. 每个任务对单条数据执行 Pipeline
      4. 结果汇总到 PipelineResult

    Args:
        pipelines: 管线列表（当前仅使用第一个管线）
        concurrency: 最大并发数
        global_context: 全局上下文数据，每个 item 的 PipelineContext 初始化时继承
    """

    def __init__(
        self,
        pipelines: list[Pipeline],
        concurrency: int = 5,
        global_context: dict[str, Any] | None = None,
    ) -> None:
        if not pipelines:
            raise PipelineError("PipelineEngine requires at least one pipeline")
        self._pipelines = pipelines
        self._concurrency = concurrency
        self._global_context = global_context

    async def execute(self, items: Iterable[Any]) -> PipelineResult:
        """执行管道 — 异步入口。

        Args:
            items: 待处理的批量数据

        Returns:
            PipelineResult: 执行结果汇总
        """
        pipeline = self._pipelines[0]
        item_list = list(items)
        total = len(item_list)
        start_time = time.monotonic()

        logger.info(
            "PipelineEngine starting: pipeline=%s total=%d concurrency=%d",
            pipeline.name, total, self._concurrency,
        )

        result = PipelineResult(pipeline_name=pipeline.name, total=total)
        semaphore = asyncio.Semaphore(self._concurrency)
        errors: list[ItemError] = []
        succeeded_count = 0
        skipped_count = 0
        completed_count = 0
        _log_interval = max(1, total // 20)  # 每5%打印一次进度

        async def _process_item(item: Any) -> None:
            """处理单条数据，受 Semaphore 控制并发。"""
            nonlocal succeeded_count, skipped_count, completed_count
            async with semaphore:
                ctx = PipelineContext(pipeline_name=pipeline.name, item=item, init_data=self._global_context)
                try:
                    stage_result = await pipeline.process(item, ctx)
                    if stage_result.success:
                        succeeded_count += 1
                    else:
                        skipped_count += 1
                except (PipelineStageError, PipelineAspectError) as e:
                    # 执行 Aspect 的 on_error 钩子
                    for aspect in pipeline.aspects:
                        try:
                            await aspect.on_error(item, ctx, e)
                        except Exception:
                            logger.warning(
                                "Aspect [%s].on_error failed for item %s",
                                aspect.name, item, exc_info=True,
                            )
                    errors.append(ItemError(
                        item=item,
                        stage_name=getattr(e, "stage_name", getattr(e, "aspect_name", "unknown")),
                        error=str(e),
                    ))
                finally:
                    completed_count += 1
                    if completed_count % _log_interval == 0 or completed_count == total:
                        elapsed_s = time.monotonic() - start_time
                        rate = completed_count / elapsed_s if elapsed_s > 0 else 0
                        eta_s = (total - completed_count) / rate if rate > 0 else 0
                        logger.info(
                            "PipelineEngine progress: pipeline=%s %d/%d (%.0f%%) "
                            "succeeded=%d failed=%d skipped=%d rate=%.1f/s eta=%.0fs",
                            pipeline.name, completed_count, total,
                            completed_count / total * 100,
                            succeeded_count, len(errors), skipped_count,
                            rate, eta_s,
                        )

        # 并发执行所有任务
        await asyncio.gather(*[_process_item(item) for item in item_list])

        elapsed = int((time.monotonic() - start_time) * 1000)
        result.succeeded = succeeded_count
        result.failed = len(errors)
        result.skipped = skipped_count
        result.errors = errors
        result.duration_ms = elapsed

        logger.info(
            "PipelineEngine completed: pipeline=%s total=%d succeeded=%d failed=%d skipped=%d duration=%dms",
            pipeline.name, total, result.succeeded, result.failed, result.skipped, elapsed,
        )

        return result
