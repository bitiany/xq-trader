"""A股个股资金流向采集任务（东方财富数据源）。

数据源：Tushare moneyflow_dc 接口，采集东方财富个股资金流向数据写入 FundFlowIndividual 表。
管线流程（每个标的串行执行）：
  WatermarkAspect(前切) → DownloadStage → CleanStage → PersistStage → WatermarkAspect(后切)

字段映射（moneyflow_dc → FundFlowIndividual）：
  ts_code → symbol
  trade_date → trade_date
  close → close
  pct_change → pct_change
  net_amount → main_net_amt（主力净流入额）
  net_amount_rate → main_net_pct（主力净流入占比）
  buy_elg_amount → huge_net_amt（超大单净流入额）
  buy_elg_amount_rate → huge_net_pct（超大单净流入占比）
  buy_lg_amount → big_net_amt（大单净流入额）
  buy_lg_amount_rate → big_net_pct（大单净流入占比）
  buy_md_amount → mid_net_amt（中单净流入额）
  buy_md_amount_rate → mid_net_pct（中单净流入占比）
  buy_sm_amount → small_net_amt（小单净流入额）
  buy_sm_amount_rate → small_net_pct（小单净流入占比）

水位管理（WatermarkAspect）：
  - 前切：若指定 collect_date 则以该日期为起始；否则查询水位日期作为增量起始时间
  - 后切：持久化成功后更新水位日期为参考日期（当前或前一交易日）
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from framework.commons.logger import get_logger
from framework.commons.utils.data_converter import DataFrameToModelConverter
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
from xqtrader.broker.services.tushare_data_collector import TushareDataCollector
from xqtrader.domain.market.models.fund_flow import FundFlowIndividual
from xqtrader.domain.security.models import Security

logger = get_logger(__name__)

_collector = TushareDataCollector()

# moneyflow_dc 接口字段 → FundFlowIndividual 模型字段
_DC_COLUMN_MAPPING: dict[str, str] = {
    "ts_code": "symbol",
    "net_amount": "main_net_amt",
    "net_amount_rate": "main_net_pct",
    "buy_elg_amount": "huge_net_amt",
    "buy_elg_amount_rate": "huge_net_pct",
    "buy_lg_amount": "big_net_amt",
    "buy_lg_amount_rate": "big_net_pct",
    "buy_md_amount": "mid_net_amt",
    "buy_md_amount_rate": "mid_net_pct",
    "buy_sm_amount": "small_net_amt",
    "buy_sm_amount_rate": "small_net_pct",
}


class FundFlowDcError(PipelineError):
    """个股资金流向采集异常基类。"""


class DownloadError(FundFlowDcError):
    """下载阶段异常。"""


class PersistError(FundFlowDcError):
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

            df = await _collector.fetch_moneyflow_dc(
                ts_code=stock_code,
                start_date=ts_start,
                end_date=ts_end,
            )

            if df is None or df.empty:
                logger.debug("无数据: %s range=%s~%s", stock_code, start_date, end_date)
                ctx.set("download_data", None)
                ctx.set("row_count", 0)
                ctx.set("skip_persist", True)
            else:
                ctx.set("download_data", df)
                ctx.set("row_count", len(df))
                ctx.set("skip_persist", False)
                ctx.set("data_source", "dc")

            return StageResult.ok(data={"stock_code": stock_code, "rows": ctx.get("row_count", 0)})
        except Exception as e:
            raise DownloadError(f"下载失败 {stock_code}: {e}") from e


class CleanStage(Stage):
    """清洗阶段 — 对资金流向数据进行质量校验和修复。"""

    _NUMERIC_COLS = [
        "close", "pct_change",
        "main_net_amt", "main_net_pct",
        "huge_net_amt", "huge_net_pct",
        "big_net_amt", "big_net_pct",
        "mid_net_amt", "mid_net_pct",
        "small_net_amt", "small_net_pct",
    ]

    @property
    def name(self) -> str:
        return "clean"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        stock_code: str = item

        if ctx.get("skip_persist"):
            return StageResult.ok(data={"stock_code": stock_code, "cleaned": 0})

        df: pd.DataFrame | None = ctx.get("download_data")
        if df is None or df.empty:
            return StageResult.ok(data={"stock_code": stock_code, "cleaned": 0})

        initial_len = len(df)

        # 1. 列名映射
        df = df.rename(columns=_DC_COLUMN_MAPPING)

        # 2. trade_date 格式统一为 YYYY-MM-DD（moneyflow_dc 返回 YYYYMMDD）
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")

        # 3. 删除 trade_date 为空
        df = df.dropna(subset=["trade_date"])
        if df.empty:
            ctx.set("download_data", df)
            ctx.set("row_count", 0)
            return StageResult.ok(data={"stock_code": stock_code, "cleaned": 0})

        # 4. 数值列强制转 numeric
        for col in self._NUMERIC_COLS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 5. net_mf_amt（全部净流入额）在 DC 数据源下无实际意义：
        #    各档净流入之和因买卖守恒恒等于 0，不填充该字段

        # 6. 数值列精度统一 4 位小数
        for col in self._NUMERIC_COLS:
            if col in df.columns:
                df[col] = df[col].round(4)

        # 7. 删除 symbol 或 trade_date 仍有 NaN 的行
        df = df.dropna(subset=["symbol", "trade_date"])

        df = df.reset_index(drop=True)
        ctx.set("download_data", df)
        ctx.set("row_count", len(df))

        cleaned = initial_len - len(df)
        if cleaned > 0:
            logger.debug("清洗: %s removed %d invalid rows", stock_code, cleaned)

        return StageResult.ok(data={"stock_code": stock_code, "cleaned": len(df)})


class PersistStage(Stage):
    """持久化阶段 — 将资金流向数据写入 FundFlowIndividual 表。"""

    _CUSTOM_TRANSFORMS = {
        "trade_date": lambda v: date.fromisoformat(str(v)) if v and str(v) != "nan" else None,
    }

    _UPDATE_FIELDS = [
        "close", "pct_change",
        "main_net_amt", "main_net_pct",
        "huge_net_amt", "huge_net_pct",
        "big_net_amt", "big_net_pct",
        "mid_net_amt", "mid_net_pct",
        "small_net_amt", "small_net_pct",
    ]

    @property
    def name(self) -> str:
        return "persist"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        stock_code: str = item

        if ctx.get("skip_persist"):
            return StageResult.ok(data={"stock_code": stock_code, "persisted": 0})

        df: pd.DataFrame | None = ctx.get("download_data")
        if df is None or df.empty:
            return StageResult.ok(data={"stock_code": stock_code, "persisted": 0})

        try:
            # 设置 source 列
            df["source"] = ctx.get("data_source", "dc")

            instances = DataFrameToModelConverter.convert(
                df=df,
                model_class=FundFlowIndividual,
                custom_transforms=self._CUSTOM_TRANSFORMS,
            )

            if not instances:
                return StageResult.ok(data={"stock_code": stock_code, "persisted": 0})

            count = await FundFlowIndividual.bulk_create_or_update(
                instances,  # type: ignore[arg-type]
                on_conflict=["symbol", "trade_date", "source"],
                update_fields=self._UPDATE_FIELDS,
                batch_size=100,
            )

            ctx.set("persisted_count", count)
            logger.debug("持久化完成: %s rows=%d", stock_code, count)
            return StageResult.ok(data={"stock_code": stock_code, "persisted": count})
        except Exception as e:
            raise PersistError(f"持久化失败 {stock_code}: {e}") from e


class FundFlowDcCollectTask(BaseTask):
    """A股个股资金流向采集任务（东方财富数据源）。

    入参：
      - pipeline_name: 管线名称（默认 fund_flow_dc）
      - concurrency: 并发数（默认 3，tushare 有频率限制不宜过高）
      - stock_codes: 股票代码列表（为空时采集全市场）
      - max_count: 最大标的数量（用于测试，0 表示不限）
      - collect_date: 采集起始日期（格式 YYYY-MM-DD，为空时按水位日期增量采集）
    """

    task_name = "market.fund_flow_dc_collect"
    description = "A股个股资金流向采集-东方财富数据源（管道引擎并发）"
    time_limit = 1800
    soft_time_limit = 1770

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        pipeline_name = kwargs.get("pipeline_name", "fund_flow_dc")
        concurrency = kwargs.get("concurrency", 3)
        stock_codes: list[str] | None = kwargs.get("stock_codes")
        max_count: int = kwargs.get("max_count", 0)
        collect_date: str | None = kwargs.get("collect_date")

        # 获取标的列表
        if not stock_codes:
            stock_codes = await self._get_all_stock_codes()
            if not stock_codes:
                logger.warning("未找到任何标的代码")
                return {"total": 0, "succeeded": 0, "failed": 0}

        # 限制标的数量（用于测试）
        if max_count > 0 and len(stock_codes) > max_count:
            stock_codes = stock_codes[:max_count]
            logger.debug("限制标的数量: max_count=%d", max_count)

        # 构建全局上下文
        global_ctx: dict[str, Any] = {}
        if collect_date:
            global_ctx["collect_date"] = collect_date

        logger.info(
            "开始采集: pipeline=%s concurrency=%d stocks=%d collect_date=%s",
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
        logger.debug("全市场标的数: %d", len(codes))
        return codes
