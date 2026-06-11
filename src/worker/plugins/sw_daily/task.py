"""申万行业日线行情采集任务。

数据源：Tushare (sw_daily)，采集申万行业日线行情写入 SwDaily 表。
管线流程（每个标的串行执行）：
  WatermarkAspect(前切) → DownloadStage → CleanStage → PersistStage → WatermarkAspect(后切)

水位管理（WatermarkAspect）：
  - 前切：若指定 collect_date 则以该日期为起始；否则查询水位日期作为增量起始时间
  - 后切：持久化成功后按数据实际最新日期更新水位
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
from worker.plugins.daily_incremental.stages.sw_daily_stage import (
    clean_sw_daily_data,
    persist_sw_daily_data,
)
from xqtrader.broker.services.tushare_data_collector import TushareDataCollector
from xqtrader.domain.index.models.sw_industry import SwIndustry

logger = get_logger(__name__)

_collector = TushareDataCollector()


class SwDailyError(PipelineError):
    """申万行业日线采集异常基类。"""


class DownloadError(SwDailyError):
    """下载阶段异常。"""


class PersistError(SwDailyError):
    """持久化阶段异常。"""


class DownloadStage(Stage):
    """下载阶段 — 调用 TushareDataCollector 获取申万行业日线行情数据。"""

    @property
    def name(self) -> str:
        return "download"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        ts_code: str = item
        start_date = ctx.get("start_date", "")
        end_date = ctx.get("end_date", "")

        if ctx.get("is_up_to_date"):
            return StageResult.ok(data={"ts_code": ts_code, "rows": 0, "skipped": True})

        if not start_date:
            return StageResult.fail(f"缺少 start_date，跳过 {ts_code}")

        try:
            sd = start_date.replace("-", "")
            ed = end_date.replace("-", "") if end_date else ""
            df = await _collector.fetch_sw_daily(
                ts_code=ts_code,
                start_date=sd,
                end_date=ed,
            )
            if df is None or df.empty:
                logger.debug("[sw_daily.collect] 无数据: %s range=%s~%s", ts_code, start_date, end_date)
                ctx.set("download_data", None)
                ctx.set("row_count", 0)
                ctx.set("skip_persist", True)
            else:
                ctx.set("download_data", df)
                ctx.set("row_count", len(df))
                ctx.set("skip_persist", False)

            return StageResult.ok(data={"ts_code": ts_code, "rows": ctx.get("row_count", 0)})
        except Exception as e:
            raise DownloadError(f"下载失败 {ts_code}: {e}") from e


class CleanStage(Stage):
    """清洗阶段 — 对申万行业日线数据进行质量校验和修复。"""

    @property
    def name(self) -> str:
        return "clean"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        ts_code: str = item

        if ctx.get("skip_persist"):
            return StageResult.ok(data={"ts_code": ts_code, "cleaned": 0})

        df = ctx.get("download_data")
        if df is None or df.empty:
            return StageResult.ok(data={"ts_code": ts_code, "cleaned": 0})

        initial_len = len(df)
        df = clean_sw_daily_data(df)

        ctx.set("download_data", df)
        ctx.set("row_count", len(df))

        cleaned = initial_len - len(df)
        if cleaned > 0:
            logger.debug("[sw_daily.collect] 清洗: %s removed %d invalid rows", ts_code, cleaned)

        return StageResult.ok(data={"ts_code": ts_code, "cleaned": len(df)})


class PersistStage(Stage):
    """持久化阶段 — 将申万行业日线数据写入 SwDaily 表。"""

    @property
    def name(self) -> str:
        return "persist"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        ts_code: str = item

        if ctx.get("skip_persist"):
            return StageResult.ok(data={"ts_code": ts_code, "persisted": 0})

        df = ctx.get("download_data")
        if df is None or df.empty:
            return StageResult.ok(data={"ts_code": ts_code, "persisted": 0})

        try:
            df["source"] = "tushare"

            count = await persist_sw_daily_data(df)

            ctx.set("persisted_count", count)
            # 记录数据的最新日期，供水位更新使用
            if count > 0 and "trade_date" in df.columns:
                max_td = df["trade_date"].map(
                    lambda v: date_type.fromisoformat(str(v))
                ).max()
                ctx.set("max_trade_date", max_td)

            logger.debug("[sw_daily.collect] 持久化完成: %s rows=%d", ts_code, count)
            return StageResult.ok(data={"ts_code": ts_code, "persisted": count})
        except Exception as e:
            raise PersistError(f"持久化失败 {ts_code}: {e}") from e


class SwDailyCollectTask(BaseTask):
    """申万行业日线行情采集任务。

    入参：
      - pipeline_name: 管线名称（默认 sw_daily）
      - concurrency: 并发数（默认 5）
      - ts_codes: 行业代码列表（为空时采集全市场申万行业）
      - max_count: 最大标的数量（用于测试，0 表示不限）
      - collect_date: 采集起始日期（格式 YYYY-MM-DD，为空时按水位日期增量采集）
    """

    task_name = "market.sw_daily_collect"
    description = "申万行业日线行情采集（管道引擎并发）"
    time_limit = 3600
    soft_time_limit = 3570

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        pipeline_name = kwargs.get("pipeline_name", "sw_daily")
        concurrency = kwargs.get("concurrency", 5)
        ts_codes: list[str] | None = kwargs.get("ts_codes")
        max_count: int = kwargs.get("max_count", 0)
        collect_date: str | None = kwargs.get("collect_date")

        # 获取行业代码列表
        if not ts_codes:
            ts_codes = await self._get_all_sw_codes()
            if not ts_codes:
                logger.warning("[sw_daily.collect] 未找到任何申万行业代码")
                return {"total": 0, "succeeded": 0, "failed": 0}

        # 限制标的数量（用于测试）
        if max_count > 0 and len(ts_codes) > max_count:
            ts_codes = ts_codes[:max_count]
            logger.debug("[sw_daily.collect] 限制标的数量: max_count=%d", max_count)

        # 构建全局上下文
        global_ctx: dict[str, Any] = {}
        if collect_date:
            global_ctx["collect_date"] = collect_date

        logger.info(
            "[sw_daily.collect] 开始采集: pipeline=%s concurrency=%d codes=%d collect_date=%s",
            pipeline_name, concurrency, len(ts_codes), collect_date or "按水位",
        )

        # 组装管线: download → clean → persist
        pipeline = Pipeline(
            name=pipeline_name,
            stages=[DownloadStage(), CleanStage(), PersistStage()],
            aspects=[WatermarkAspect(pipeline_name=pipeline_name)],
        )

        # 执行管道引擎
        engine = PipelineEngine(
            pipelines=[pipeline],
            concurrency=concurrency,
            global_context=global_ctx,
        )
        result = await engine.execute(ts_codes)

        return result.to_dict()

    @staticmethod
    async def _get_all_sw_codes() -> list[str]:
        """获取全市场申万行业指数代码（仅含 index_code 的行业）。"""
        rows = await SwIndustry.filter(order_by=SwIndustry.industry_code.asc())
        codes = [row.index_code for row in rows if row.index_code]
        logger.debug("[sw_daily.collect] 全市场申万行业数: %d", len(codes))
        return codes
