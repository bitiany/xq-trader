"""因子日频计算任务 — 基于 PipelineEngine 的逐标的批量因子计算。

核心流程：
  1. 确定日期范围（水位增量 / start_date全量回补）
  2. 获取标的列表（过滤ST/退市）
  3. 构建 Pipeline（Load → Calc → Persist）
  4. PipelineEngine 逐标的并发执行
  5. 更新水位
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from framework.commons.logger import get_logger
from framework.pipeline import Pipeline, PipelineEngine
from framework.scheduler.base_task import BaseTask
from worker.plugins.factor_compute.pipeline.calc_stage import FactorCalcStage
from worker.plugins.factor_compute.pipeline.load_stage import FactorLoadStage
from worker.plugins.factor_compute.pipeline.persist_stage import FactorPersistStage
from worker.plugins.factor_compute.plugins.base import FactorPluginRegistry
from worker.plugins.factor_compute.plugins.fund_flow import FundFlowPlugin
from worker.plugins.factor_compute.plugins.fundamental import FundamentalPlugin
from worker.plugins.factor_compute.plugins.momentum import MomentumPlugin
from worker.plugins.factor_compute.plugins.quantitative import QuantitativePlugin
from worker.plugins.factor_compute.plugins.risk import RiskPlugin
from worker.plugins.factor_compute.plugins.technical import TechnicalPlugin
from worker.plugins.factor_compute.plugins.valuation import ValuationPlugin
from xqtrader.domain.index.index_daily import IndexDaily
from xqtrader.domain.security.models import Security
from xqtrader.domain.watermark.models.collect_watermark import CollectWatermark
from xqtrader.domain.watermark.models.trade_calendar import TradeCalendar

logger = get_logger(__name__)

# 因子计算水位标识
_FACTOR_WATERMARK_PIPELINE = "factor_compute"
_FACTOR_WATERMARK_CODE = "daily"


class FactorComputeTask(BaseTask):
    """因子日频计算任务 — 基于 PipelineEngine 的逐标的批量因子计算。

    入参：
      - start_date: 起始日期（格式 YYYY-MM-DD，用于全量回补，覆盖水位）
      - trade_date: 单日计算日期（格式 YYYY-MM-DD，优先级低于 start_date）
      - stock_codes: 股票代码列表（为空时计算全市场）
      - max_count: 最大标的数量（用于测试，0 表示不限）
      - factor_ids: 因子ID列表（为空时计算全部已注册因子）
      - concurrency: 并发数（默认5）
    """

    task_name = "factor.compute_daily"
    description = "因子日频计算（PipelineEngine批量）"
    time_limit = 7200
    soft_time_limit = 7170

    def _build_registry(self) -> FactorPluginRegistry:
        """构建因子插件注册表，注册所有因子类别。"""
        registry = FactorPluginRegistry()
        registry.register(ValuationPlugin())
        registry.register(FundamentalPlugin())
        registry.register(TechnicalPlugin())
        registry.register(MomentumPlugin())
        registry.register(RiskPlugin())
        registry.register(QuantitativePlugin())
        registry.register(FundFlowPlugin())
        return registry

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        start_date_str: str | None = kwargs.get("start_date")
        trade_date_str: str | None = kwargs.get("trade_date")
        stock_codes: list[str] | None = kwargs.get("stock_codes")
        max_count: int = kwargs.get("max_count", 0)
        factor_ids: list[str] | None = kwargs.get("factor_ids")
        concurrency: int = kwargs.get("concurrency", 5)

        # 1. 确定日期范围
        trade_dates = await self._resolve_trade_dates(start_date_str, trade_date_str)
        if not trade_dates:
            logger.warning("未找到有效交易日")
            return {"total": 0, "succeeded": 0, "failed": 0, "trade_dates": []}

        logger.info(
            "日期范围: %s ~ %s (%d个交易日)",
            trade_dates[0], trade_dates[-1], len(trade_dates),
        )

        # 2. 构建插件注册表
        registry = self._build_registry()

        # 3. 过滤 factor_ids
        if factor_ids:
            all_ids = set(registry.all_factor_ids())
            factor_ids = [fid for fid in factor_ids if fid in all_ids]
            if not factor_ids:
                factor_ids = None

        # 4. 获取标的列表
        if not stock_codes:
            stock_codes = await self._get_filtered_stock_codes()
            if not stock_codes:
                logger.warning("未找到任何标的代码")
                return {
                    "total": 0, "succeeded": 0, "failed": 0,
                    "trade_dates": [str(d) for d in trade_dates],
                }

        if max_count > 0 and len(stock_codes) > max_count:
            stock_codes = stock_codes[:max_count]
            logger.info("限制标的数量: max_count=%d", max_count)

        logger.info(
            "开始因子计算: dates=%d stocks=%d factor_ids=%s concurrency=%d",
            len(trade_dates), len(stock_codes),
            factor_ids if factor_ids else "全部", concurrency,
        )

        # 5. 构建 Pipeline
        pipeline = Pipeline(
            name="factor_compute",
            stages=[
                FactorLoadStage(registry=registry, trade_dates=trade_dates),
                FactorCalcStage(registry=registry, trade_dates=trade_dates, factor_ids=factor_ids),
                FactorPersistStage(),
            ],
        )

        # 6. 执行 PipelineEngine
        # 预加载指数K线到全局上下文，避免每个标的重复加载
        global_ctx: dict[str, Any] = {}
        end_date = trade_dates[-1]
        index_rows = await IndexDaily.filter(
            symbol="000300.SH",
            trade_date__lte=end_date,
            order_by=IndexDaily.trade_date.asc(),
        )
        if index_rows:
            global_ctx["index_kline_df"] = pd.DataFrame([
                {"trade_date": r.trade_date, "close": r.close} for r in index_rows
            ])

        engine = PipelineEngine(
            pipelines=[pipeline],
            concurrency=concurrency,
            global_context=global_ctx,
        )
        result = await engine.execute(stock_codes)

        # 7. 更新水位
        await self._update_watermark(trade_dates[-1])

        result_dict = result.to_dict()
        result_dict["trade_dates"] = [str(d) for d in trade_dates]
        return result_dict

    async def _resolve_trade_dates(
        self,
        start_date_str: str | None,
        trade_date_str: str | None,
    ) -> list[date]:
        """解析交易日列表。

        优先级：
          1. start_date 指定 → 从 start_date 到最新交易日（全量回补）
          2. trade_date 指定 → 仅计算该日
          3. 均未指定 → 从水位日期到最新交易日（增量计算）
        """
        latest_date = await self._get_latest_trade_date()
        if latest_date is None:
            return []

        # 模式1: start_date 全量回补
        if start_date_str:
            try:
                start_date = date.fromisoformat(start_date_str)
            except ValueError:
                logger.warning("无效的起始日期格式: %s", start_date_str)
                return []
            return await TradeCalendar.get_trade_dates(start=start_date, end=latest_date)

        # 模式2: trade_date 单日计算
        if trade_date_str:
            try:
                td = date.fromisoformat(trade_date_str)
            except ValueError:
                logger.warning("无效的交易日期格式: %s", trade_date_str)
                return []
            return [td]

        # 模式3: 增量计算（从水位到最新）
        watermark_date = await self._get_watermark_date()
        if watermark_date is not None:
            next_day = watermark_date + timedelta(days=1)
            dates = await TradeCalendar.get_trade_dates(start=next_day, end=latest_date)
            if dates:
                logger.info("增量计算: watermark=%s 新增=%d天", watermark_date, len(dates))
            else:
                logger.info("水位已是最新: watermark=%s", watermark_date)
            return dates

        # 无水位：默认计算最近1个交易日
        logger.info("无水位记录，计算最近1个交易日")
        return [latest_date]

    @staticmethod
    async def _get_latest_trade_date() -> date | None:
        """获取最新交易日。"""
        tz = ZoneInfo("Asia/Shanghai")
        now = datetime.now(tz)
        ref_date = now.date()
        if now.hour < 15:
            ref_date = ref_date - timedelta(days=1)
        return await TradeCalendar.get_latest_trade_date(
            exchange="SSE", on_or_before=ref_date,
        )

    @staticmethod
    async def _get_watermark_date() -> date | None:
        """获取因子计算水位日期。"""
        rows = await CollectWatermark.filter(
            pipeline_name=_FACTOR_WATERMARK_PIPELINE,
            watermark_code=_FACTOR_WATERMARK_CODE,
        )
        if rows and rows[0].watermark_date:
            return rows[0].watermark_date
        return None

    @staticmethod
    async def _update_watermark(latest_date: date) -> None:
        """更新因子计算水位。"""
        rows = await CollectWatermark.filter(
            pipeline_name=_FACTOR_WATERMARK_PIPELINE,
            watermark_code=_FACTOR_WATERMARK_CODE,
        )
        if rows:
            wm = rows[0]
            wm.watermark_date = latest_date
            wm.record_count = (wm.record_count or 0) + 1
            await wm.save()
        else:
            wm = CollectWatermark(
                pipeline_name=_FACTOR_WATERMARK_PIPELINE,
                watermark_code=_FACTOR_WATERMARK_CODE,
                watermark_date=latest_date,
                record_count=1,
                status="active",
            )
            await wm.save()
        logger.info("水位更新: %s", latest_date)

    @staticmethod
    async def _get_filtered_stock_codes() -> list[str]:
        """获取过滤后的标的代码列表。

        过滤规则：
          - list_status="L"（仅上市状态）
          - 排除ST/*ST股票
        """
        rows = await Security.filter(
            list_status="L",
            order_by=Security.symbol.asc(),
        )
        codes: list[str] = []
        for row in rows:
            name = row.name or ""
            if "ST" in name or "*ST" in name:
                continue
            codes.append(row.symbol)
        logger.info("标的过滤: 总数=%d 过滤后=%d", len(rows), len(codes))
        return codes
