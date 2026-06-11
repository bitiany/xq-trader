"""A股个股资金流向采集任务（Tushare 原生数据源）。

数据源：Tushare moneyflow 接口，采集个股资金流向数据写入 FundFlowIndividual 表。
管线流程（每个标的串行执行）：
  WatermarkAspect(前切) → DownloadStage → CleanStage → PersistStage → WatermarkAspect(后切)

字段映射与计算（moneyflow → FundFlowIndividual）：
  ts_code → symbol
  trade_date → trade_date
  buy_elg_amount → huge_buy_amt（特大单买入金额，万元）
  sell_elg_amount → huge_sell_amt（特大单卖出金额，万元）
  buy_lg_amount → big_buy_amt（大单买入金额，万元）
  sell_lg_amount → big_sell_amt（大单卖出金额，万元）
  buy_md_amount → mid_buy_amt（中单买入金额，万元）
  sell_md_amount → mid_sell_amt（中单卖出金额，万元）
  buy_sm_amount → small_buy_amt（小单买入金额，万元）
  sell_sm_amount → small_sell_amt（小单卖出金额，万元）
  net_mf_amount → net_mf_amt（净流入额，万元）

  计算字段：
  huge_net_amt = buy_elg_amount - sell_elg_amount
  big_net_amt = buy_lg_amount - sell_lg_amount
  mid_net_amt = buy_md_amount - sell_md_amount
  small_net_amt = buy_sm_amount - sell_sm_amount
  main_net_amt = huge_net_amt + big_net_amt
  huge_net_pct = huge_net_amt / (buy_elg_amount + sell_elg_amount) * 100
  big_net_pct = big_net_amt / (buy_lg_amount + sell_lg_amount) * 100
  mid_net_pct = mid_net_amt / (buy_md_amount + sell_md_amount) * 100
  small_net_pct = small_net_amt / (buy_sm_amount + sell_sm_amount) * 100
  main_net_pct = main_net_amt / (huge_buy+sell + big_buy+sell) * 100

水位管理（WatermarkAspect）：
  - 前切：若指定 collect_date 则以该日期为起始；否则查询水位日期作为增量起始时间
  - 后切：持久化成功后更新水位日期为参考日期（当前或前一交易日）
"""

from __future__ import annotations

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
from worker.plugins.daily_incremental.stages.fund_flow_stage import (
    clean_fund_flow_data,
    persist_fund_flow_data,
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


class FundFlowError(PipelineError):
    """个股资金流向采集异常基类。"""


class DownloadError(FundFlowError):
    """下载阶段异常。"""


class PersistError(FundFlowError):
    """持久化阶段异常。"""


class DownloadStage(Stage):
    """下载阶段 — 调用 TushareDataCollector 获取个股资金流向数据。"""

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
            # start_date/end_date 为 YYYY-MM-DD 格式，tushare 需要 YYYYMMDD
            ts_start = start_date.replace("-", "")
            ts_end = end_date.replace("-", "") if end_date else ""

            df = await _get_collector().fetch_moneyflow(
                ts_code=stock_code,
                start_date=ts_start,
                end_date=ts_end,
            )

            if df is None or df.empty:
                logger.debug("[fund_flow.collect] 无数据: %s range=%s~%s", stock_code, start_date, end_date)
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
    """清洗阶段 — 对资金流向数据进行质量校验、计算净流入额和占比。"""

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
        df = clean_fund_flow_data(df)

        ctx.set("download_data", df)
        ctx.set("row_count", len(df))

        cleaned = initial_len - len(df)
        if cleaned > 0:
            logger.debug("[fund_flow.collect] 清洗: %s removed %d invalid rows", stock_code, cleaned)

        return StageResult.ok(data={"stock_code": stock_code, "cleaned": len(df)})


class PersistStage(Stage):
    """持久化阶段 — 将资金流向数据写入 FundFlowIndividual 表。"""

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
            count = await persist_fund_flow_data(df)

            ctx.set("persisted_count", count)
            logger.debug("[fund_flow.collect] 持久化完成: %s rows=%d", stock_code, count)
            return StageResult.ok(data={"stock_code": stock_code, "persisted": count})
        except Exception as e:
            raise PersistError(f"持久化失败 {stock_code}: {e}") from e


class FundFlowCollectTask(BaseTask):
    """A股个股资金流向采集任务（Tushare 原生数据源）。

    入参：
      - pipeline_name: 管线名称（默认 fund_flow）
      - concurrency: 并发数（默认 50，实际 API 速率由 TushareDataCollector 滑动窗口限流控制）
      - stock_codes: 股票代码列表（为空时采集全市场）
      - max_count: 最大标的数量（用于测试，0 表示不限）
      - collect_date: 采集起始日期（格式 YYYY-MM-DD，为空时按水位日期增量采集）
    """

    task_name = "market.fund_flow_collect"
    description = "A股个股资金流向采集-Tushare原生数据源（管道引擎并发）"
    time_limit = 14400
    soft_time_limit = 14370

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        pipeline_name = kwargs.get("pipeline_name", "fund_flow")
        concurrency = kwargs.get("concurrency", 50)
        stock_codes: list[str] | None = kwargs.get("stock_codes")
        max_count: int = kwargs.get("max_count", 0)
        collect_date: str | None = kwargs.get("collect_date")

        # 获取标的列表
        if not stock_codes:
            stock_codes = await self._get_all_stock_codes()
            if not stock_codes:
                logger.warning("[fund_flow.collect] 未找到任何标的代码")
                return {"total": 0, "succeeded": 0, "failed": 0}

        # 限制标的数量（用于测试）
        if max_count > 0 and len(stock_codes) > max_count:
            stock_codes = stock_codes[:max_count]
            logger.debug("[fund_flow.collect] 限制标的数量: max_count=%d", max_count)

        # 构建全局上下文
        global_ctx: dict[str, Any] = {}
        if collect_date:
            global_ctx["collect_date"] = collect_date

        logger.info(
            "[fund_flow.collect] 开始采集: pipeline=%s concurrency=%d stocks=%d collect_date=%s",
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
        logger.debug("[fund_flow.collect] 全市场标的数: %d", len(codes))
        return codes
