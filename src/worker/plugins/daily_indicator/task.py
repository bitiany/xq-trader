"""A股每日指标采集任务（Tushare daily_basic 数据源）。

数据源：Tushare daily_basic 接口，采集每日指标数据写入 DailyIndicator 表。
管线流程（每个标的串行执行）：
  WatermarkAspect(前切) → DownloadStage → CleanStage → PersistStage → WatermarkAspect(后切)

字段映射（daily_basic → DailyIndicator）：
  ts_code → symbol
  trade_date → trade_date
  close/turnover_rate/turnover_rate_f/volume_ratio → 同名
  pe/pe_ttm/pb/ps/ps_ttm/dv_ratio/dv_ttm → 同名
  total_share/float_share/free_share/total_mv/circ_mv → 同名
  ev/ebitda/ev_ebitda/peg/pcf → 同名

水位管理（WatermarkAspect）：
  - 前切：若指定 collect_date 则以该日期为起始；否则查询水位日期作为增量起始时间
  - 后切：持久化成功后更新水位日期为参考日期（当前或前一交易日）
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
from worker.plugins.daily_incremental.stages.daily_indicator_stage import (
    clean_daily_indicator_data,
    persist_daily_indicator_data,
)
from xqtrader.broker.services.tushare_data_collector import TushareDataCollector
from xqtrader.domain.security.models import Security

logger = get_logger(__name__)

_collector: TushareDataCollector | None = None


def _get_collector() -> TushareDataCollector:
    """延迟初始化 TushareDataCollector 单例。"""
    global _collector  # noqa: PLW0603
    if _collector is None:
        _collector = TushareDataCollector()
    return _collector


class DailyIndicatorError(PipelineError):
    """每日指标采集异常基类。"""


class DownloadError(DailyIndicatorError):
    """下载阶段异常。"""


class PersistError(DailyIndicatorError):
    """持久化阶段异常。"""


class DownloadStage(Stage):
    """下载阶段 — 调用 TushareDataCollector 获取每日指标数据。"""

    @property
    def name(self) -> str:
        return "download"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        stock_code: str = item
        start_date = ctx.get("start_date", "")
        end_date = ctx.get("end_date", "")

        if ctx.get("is_up_to_date"):
            return StageResult.ok(data={"stock_code": stock_code, "rows": 0, "skipped": True})

        if not start_date:
            return StageResult.fail(f"缺少 start_date，跳过 {stock_code}")

        try:
            ts_start = start_date.replace("-", "")
            ts_end = end_date.replace("-", "") if end_date else ""

            df = await _get_collector().fetch_daily_basic(
                ts_code=stock_code,
                start_date=ts_start,
                end_date=ts_end,
            )

            if df is None or df.empty:
                logger.debug(
                    "[daily_indicator.collect] 无数据: %s range=%s~%s",
                    stock_code, start_date, end_date,
                )
                ctx.set("download_data", None)
                ctx.set("row_count", 0)
                ctx.set("skip_persist", True)
            else:
                ctx.set("download_data", df)
                ctx.set("row_count", len(df))
                ctx.set("skip_persist", False)

            return StageResult.ok(data={"stock_code": stock_code, "rows": ctx.get("row_count", 0)})
        except Exception as e:
            raise DownloadError(f"下载失败 {stock_code}: {e}") from e


class CleanStage(Stage):
    """清洗阶段 — 对每日指标数据进行列映射和数值处理。"""

    @property
    def name(self) -> str:
        return "clean"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        stock_code: str = item

        if ctx.get("skip_persist"):
            return StageResult.ok(data={"stock_code": stock_code, "cleaned": 0})

        df = ctx.get("download_data")
        if df is None or df.empty:
            return StageResult.ok(data={"stock_code": stock_code, "cleaned": 0})

        initial_len = len(df)
        df = clean_daily_indicator_data(df)

        ctx.set("download_data", df)
        ctx.set("row_count", len(df))

        cleaned = initial_len - len(df)
        if cleaned > 0:
            logger.debug(
                "[daily_indicator.collect] 清洗: %s removed %d invalid rows",
                stock_code, cleaned,
            )

        return StageResult.ok(data={"stock_code": stock_code, "cleaned": len(df)})


class PersistStage(Stage):
    """持久化阶段 — 将每日指标数据写入 DailyIndicator 表。"""

    @property
    def name(self) -> str:
        return "persist"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        stock_code: str = item

        if ctx.get("skip_persist"):
            return StageResult.ok(data={"stock_code": stock_code, "persisted": 0})

        df = ctx.get("download_data")
        if df is None or df.empty:
            return StageResult.ok(data={"stock_code": stock_code, "persisted": 0})

        try:
            count = await persist_daily_indicator_data(df)

            ctx.set("persisted_count", count)
            # 记录数据的最新日期，供水位更新使用
            if count > 0 and "trade_date" in df.columns:
                max_td = df["trade_date"].map(
                    lambda v: date_type.fromisoformat(str(v))
                ).max()
                ctx.set("max_trade_date", max_td)

            logger.debug("[daily_indicator.collect] 持久化完成: %s rows=%d", stock_code, count)
            return StageResult.ok(data={"stock_code": stock_code, "persisted": count})
        except Exception as e:
            raise PersistError(f"持久化失败 {stock_code}: {e}") from e


class DailyIndicatorCollectTask(BaseTask):
    """A股每日指标采集任务（Tushare daily_basic 数据源）。

    入参：
      - pipeline_name: 管线名称（默认 daily_indicator）
      - concurrency: 并发数（默认 50）
      - stock_codes: 股票代码列表（为空时采集全市场）
      - max_count: 最大标的数量（用于测试，0 表示不限）
      - collect_date: 采集起始日期（格式 YYYY-MM-DD，为空时按水位日期增量采集）
    """

    task_name = "market.daily_indicator_collect"
    description = "A股每日指标采集-Tushare daily_basic数据源（管道引擎并发）"
    time_limit = 14400
    soft_time_limit = 14370

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        pipeline_name = kwargs.get("pipeline_name", "daily_indicator")
        concurrency = kwargs.get("concurrency", 50)
        stock_codes: list[str] | None = kwargs.get("stock_codes")
        max_count: int = kwargs.get("max_count", 0)
        collect_date: str | None = kwargs.get("collect_date")

        # 获取标的列表
        if not stock_codes:
            stock_codes = await self._get_all_stock_codes()
            if not stock_codes:
                logger.warning("[daily_indicator.collect] 未找到任何标的代码")
                return {"total": 0, "succeeded": 0, "failed": 0}

        # 限制标的数量（用于测试）
        if max_count > 0 and len(stock_codes) > max_count:
            stock_codes = stock_codes[:max_count]
            logger.debug("[daily_indicator.collect] 限制标的数量: max_count=%d", max_count)

        # 构建全局上下文
        global_ctx: dict[str, Any] = {}
        if collect_date:
            global_ctx["collect_date"] = collect_date

        logger.info(
            "[daily_indicator.collect] 开始采集: pipeline=%s concurrency=%d stocks=%d collect_date=%s",
            pipeline_name, concurrency, len(stock_codes), collect_date or "按水位",
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
        result = await engine.execute(stock_codes)

        return result.to_dict()

    @staticmethod
    async def _get_all_stock_codes() -> list[str]:
        """获取全市场 A 股标的代码。"""
        rows = await Security.filter(
            list_status="L",
            order_by=Security.symbol.asc(),
        )
        codes = [row.symbol for row in rows]
        logger.debug("[daily_indicator.collect] 全市场标的数: %d", len(codes))
        return codes
