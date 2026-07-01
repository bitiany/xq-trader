"""指数日线行情采集任务。

数据源：Tushare (index_daily)
管线流程（每个标的串行执行）：
  WatermarkAspect(前切) → DownloadStage → CleanStage → PersistStage → WatermarkAspect(后切)
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from framework.commons.logger import get_logger
from framework.pipeline import (
    Pipeline,
    PipelineContext,
    PipelineEngine,
    PipelineError,
    Stage,
    StageResult,
)
from framework.scheduler.base_task import BaseTask
from worker.plugins.aspects import WatermarkAspect
from worker.plugins.index_daily.kline_ops import (
    clean_index_kline_data,
    persist_index_kline_data,
)
from xqtrader.broker.services.tushare_data_collector import TushareDataCollector
from xqtrader.domain.index.models.index import Index

logger = get_logger(__name__)

_collector = TushareDataCollector()


class IndexDailyError(PipelineError):
    """指数日线采集异常基类。"""


class DownloadError(IndexDailyError):
    """下载阶段异常。"""


class PersistError(IndexDailyError):
    """持久化阶段异常。"""


class DownloadStage(Stage):
    """下载阶段 — 调用 Tushare index_daily 获取指数日线行情。"""

    @property
    def name(self) -> str:
        return "download"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        index_code: str = item
        start_date = ctx.get("start_date", "")
        end_date = ctx.get("end_date", "")

        if ctx.get("is_up_to_date"):
            logger.info("[index_daily.collect] 跳过(水位最新): %s", index_code)
            return StageResult.ok(data={"index_code": index_code, "rows": 0, "skipped": True})

        if not start_date:
            return StageResult.fail(f"缺少 start_date，跳过 {index_code}")

        effective_end_date = end_date if end_date else date_type.today().strftime("%Y%m%d")
        logger.info(
            "[index_daily.collect] 下载: %s range=%s~%s",
            index_code, start_date, effective_end_date,
        )
        try:
            df = await _collector.fetch_index_daily(
                ts_code=index_code,
                start_date=start_date,
                end_date=effective_end_date,
            )
            if df is None or df.empty:
                logger.info(
                    "[index_daily.collect] 无数据: %s range=%s~%s",
                    index_code, start_date, effective_end_date,
                )
                ctx.set("download_data", None)
                ctx.set("row_count", 0)
                ctx.set("skip_persist", True)
            else:
                ctx.set("download_data", df)
                ctx.set("row_count", len(df))
                ctx.set("skip_persist", False)
                logger.info(
                    "[index_daily.collect] 下载完成: %s rows=%d range=%s~%s",
                    index_code, len(df), start_date, effective_end_date,
                )

            return StageResult.ok(data={"index_code": index_code, "rows": ctx.get("row_count", 0)})
        except Exception as e:
            raise DownloadError(f"下载失败 {index_code}: {e}") from e


class CleanStage(Stage):
    """清洗阶段 — 对指数K线数据进行质量校验和修复。"""

    @property
    def name(self) -> str:
        return "clean"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        index_code: str = item

        if ctx.get("skip_persist"):
            return StageResult.ok(data={"index_code": index_code, "cleaned": 0})

        df = ctx.get("download_data")
        if df is None or df.empty:
            return StageResult.ok(data={"index_code": index_code, "cleaned": 0})

        initial_len = len(df)
        df = clean_index_kline_data(df)

        ctx.set("download_data", df)
        ctx.set("row_count", len(df))

        cleaned = initial_len - len(df)
        if cleaned > 0:
            logger.debug("[index_daily.collect] 清洗: %s removed %d invalid rows", index_code, cleaned)

        return StageResult.ok(data={"index_code": index_code, "cleaned": len(df)})


class PersistStage(Stage):
    """持久化阶段 — 将指数K线数据写入 IndexDaily 表。"""

    @property
    def name(self) -> str:
        return "persist"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        index_code: str = item

        if ctx.get("skip_persist"):
            return StageResult.ok(data={"index_code": index_code, "persisted": 0})

        df = ctx.get("download_data")
        if df is None or df.empty:
            return StageResult.ok(data={"index_code": index_code, "persisted": 0})

        try:
            df["symbol"] = index_code
            df["source"] = "tushare"

            count = await persist_index_kline_data(df)

            ctx.set("persisted_count", count)
            if count > 0 and "trade_date" in df.columns:
                max_td = df["trade_date"].map(
                    lambda v: date_type.fromisoformat(str(v))
                ).max()
                ctx.set("max_trade_date", max_td)

            logger.debug("[index_daily.collect] 持久化完成: %s rows=%d", index_code, count)
            return StageResult.ok(data={"index_code": index_code, "persisted": count})
        except Exception as e:
            raise PersistError(f"持久化失败 {index_code}: {e}") from e


class IndexDailyCollectTask(BaseTask):
    """指数日线行情采集任务。

    入参：
      - data_type: 数据类型（默认 index_daily）
      - concurrency: 并发数（默认 5）
      - index_codes: 指数代码列表（为空时采集全市场指数）
      - max_count: 最大标的数量（用于测试，0 表示不限）
      - collect_date: 采集起始日期（格式 YYYY-MM-DD，为空时按水位日期增量采集）
    """

    task_name = "market.index_daily_collect"
    description = "指数日线行情采集（Tushare，管道引擎并发）"

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        data_type = kwargs.get("data_type", "index_daily")
        concurrency = kwargs.get("concurrency", 5)
        index_codes: list[str] | None = kwargs.get("index_codes")
        max_count: int = kwargs.get("max_count", 0)
        collect_date: str | None = kwargs.get("collect_date")

        if not index_codes:
            index_codes = await self._get_all_index_codes()
            if not index_codes:
                logger.warning("[index_daily.collect] 未找到任何指数代码")
                return {"total": 0, "succeeded": 0, "failed": 0}

        if max_count > 0 and len(index_codes) > max_count:
            index_codes = index_codes[:max_count]
            logger.debug("[index_daily.collect] 限制标的数量: max_count=%d", max_count)

        global_ctx: dict[str, Any] = {}
        if collect_date:
            global_ctx["collect_date"] = collect_date

        logger.info(
            "[index_daily.collect] 开始采集: pipeline=%s concurrency=%d indexes=%d collect_date=%s",
            data_type, concurrency, len(index_codes), collect_date or "按水位",
        )

        pipeline = Pipeline(
            name=data_type,
            stages=[DownloadStage(), CleanStage(), PersistStage()],
            aspects=[WatermarkAspect(data_type=data_type)],
        )

        engine = PipelineEngine(
            pipelines=[pipeline],
            concurrency=concurrency,
            global_context=global_ctx,
        )
        result = await engine.execute(index_codes)

        return result.to_dict()

    @staticmethod
    async def _get_all_index_codes() -> list[str]:
        """获取全市场指数代码。"""
        rows = await Index.filter(order_by=Index.index_code.asc())
        codes = [row.index_code for row in rows]
        logger.debug("[index_daily.collect] 全市场指数数: %d", len(codes))
        return codes
