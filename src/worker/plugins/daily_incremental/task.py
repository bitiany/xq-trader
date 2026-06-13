"""日行情、资金流向、每日指标、指数行情与申万行业行情增量采集任务。

按日期增量采集全市场日行情K线、资金流向、每日指标、指数行情和申万行业行情数据，
每个数据类型独立完成采集→清洗→持久化→更新水位闭环。

水位策略：
  - 每个数据类型独立检查水位，缺失水位的 Stage 跳过执行
  - 若指定 start_date，则所有 Stage 统一使用该日期
  - 若未指定 start_date，则各 Stage 按自身 data_type 的最大水位日期确定起始日期
  - 所有 Stage 均无水位且未指定 start_date → 报错
  - 标的级水位（与回补任务共享）用于过滤已采集数据，采集后按标的更新
"""

from __future__ import annotations

from datetime import date
from typing import Any

from framework.commons.logger import get_logger
from framework.scheduler.base_task import BaseTask
from worker.plugins.daily_incremental.stages.daily_indicator_stage import (
    DailyIndicatorIncrementalStage,
)
from worker.plugins.daily_incremental.stages.daily_kline_stage import (
    DailyKlineIncrementalStage,
)
from worker.plugins.daily_incremental.stages.fund_flow_stage import (
    FundFlowIncrementalStage,
)
from worker.plugins.daily_incremental.stages.index_daily_stage import (
    IndexDailyIncrementalStage,
)
from worker.plugins.daily_incremental.stages.sw_daily_stage import (
    SwDailyIncrementalStage,
)
from xqtrader.domain.watermark.models.collect_watermark import CollectWatermark
from xqtrader.domain.watermark.services.watermark_service import WatermarkService

logger = get_logger(__name__)


class DailyIncrementalTask(BaseTask):
    """日行情、资金流向、每日指标、指数行情与申万行业行情增量采集任务。

    入参：
      - start_date: 采集起始日期（格式 YYYY-MM-DD，为空时按各 Stage 标的级水位）
      - end_date: 采集结束日期（格式 YYYY-MM-DD，为空时取最新交易日）
      - kline_batch_size: QMT 标的分片大小（默认 50）
    """

    task_name = "market.daily_incremental_collect"
    description = "按日期增量采集全市场日行情K线、资金流向、每日指标、指数行情和申万行业行情数据"
    time_limit = 18000
    soft_time_limit = 17970

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        start_date_str: str | None = kwargs.get("start_date")
        end_date_str: str | None = kwargs.get("end_date")
        kline_batch_size: int = kwargs.get("kline_batch_size", 500)

        # 确定 end_date
        end_date = await self._resolve_end_date(end_date_str)

        # 各 Stage 独立确定 start_date
        kline_start = await self._resolve_stage_start(
            DailyKlineIncrementalStage.DATA_TYPE,
            start_date_str,
        )
        ff_start = await self._resolve_stage_start(
            FundFlowIncrementalStage.DATA_TYPE,
            start_date_str,
        )
        indicator_start = await self._resolve_stage_start(
            DailyIndicatorIncrementalStage.DATA_TYPE,
            start_date_str,
        )
        index_start = await self._resolve_stage_start(
            IndexDailyIncrementalStage.DATA_TYPE,
            start_date_str,
        )
        sw_start = await self._resolve_stage_start(
            SwDailyIncrementalStage.DATA_TYPE,
            start_date_str,
        )

        # 所有 Stage 均无水位且未指定 start_date → 报错
        all_no_watermark = (
            kline_start is None
            and ff_start is None
            and indicator_start is None
            and index_start is None
            and sw_start is None
        )
        if all_no_watermark:
            return {
                "status": "ERROR",
                "message": (
                    "无水位记录，请先执行全量回补任务"
                    "（daily_kline / fund_flow / daily_indicator / index_daily / sw_daily）"
                ),
            }

        results: dict[str, Any] = {"status": "SUCCESS", "end_date": str(end_date)}

        # Stage 1: 日行情增量
        if kline_start is not None and kline_start < end_date:
            logger.info(
                "[daily.incremental] 日行情增量: %s~%s", kline_start, end_date,
            )
            kline_stage = DailyKlineIncrementalStage(batch_size=kline_batch_size)
            results["daily_kline"] = await kline_stage.execute(kline_start, end_date)
        else:
            logger.info("[daily.incremental] 日行情: 无水位或已最新，跳过")
            results["daily_kline"] = {"status": "SKIPPED"}

        # Stage 2: 资金流向增量
        if ff_start is not None and ff_start < end_date:
            logger.info(
                "[daily.incremental] 资金流向增量: %s~%s", ff_start, end_date,
            )
            fund_flow_stage = FundFlowIncrementalStage()
            results["fund_flow"] = await fund_flow_stage.execute(ff_start, end_date)
        else:
            logger.info("[daily.incremental] 资金流向: 无水位或已最新，跳过")
            results["fund_flow"] = {"status": "SKIPPED"}

        # Stage 3: 每日指标增量
        if indicator_start is not None and indicator_start < end_date:
            logger.info(
                "[daily.incremental] 每日指标增量: %s~%s", indicator_start, end_date,
            )
            indicator_stage = DailyIndicatorIncrementalStage()
            results["daily_indicator"] = await indicator_stage.execute(indicator_start, end_date)
        else:
            logger.info("[daily.incremental] 每日指标: 无水位或已最新，跳过")
            results["daily_indicator"] = {"status": "SKIPPED"}

        # Stage 4: 指数行情增量
        if index_start is not None and index_start < end_date:
            logger.info(
                "[daily.incremental] 指数行情增量: %s~%s", index_start, end_date,
            )
            index_stage = IndexDailyIncrementalStage()
            results["index_daily"] = await index_stage.execute(index_start, end_date)
        else:
            logger.info("[daily.incremental] 指数行情: 无水位或已最新，跳过")
            results["index_daily"] = {"status": "SKIPPED"}

        # Stage 5: 申万行业行情增量
        if sw_start is not None and sw_start < end_date:
            logger.info(
                "[daily.incremental] 申万行业行情增量: %s~%s", sw_start, end_date,
            )
            sw_stage = SwDailyIncrementalStage()
            results["sw_daily"] = await sw_stage.execute(sw_start, end_date)
        else:
            logger.info("[daily.incremental] 申万行业行情: 无水位或已最新，跳过")
            results["sw_daily"] = {"status": "SKIPPED"}

        logger.info("[daily.incremental] 全部完成: %s", results)
        return results

    @staticmethod
    async def _resolve_end_date(end_date_str: str | None) -> date:
        """确定增量采集的结束日期。"""
        if end_date_str:
            return date.fromisoformat(end_date_str)
        ws = WatermarkService()
        latest = await ws.get_latest_trade_date()
        if latest is None:
            logger.warning("[daily.incremental] 未找到最新交易日")
            return date.today()
        return latest

    @staticmethod
    async def _resolve_stage_start(
        data_type: str,
        start_date_str: str | None,
    ) -> date | None:
        """确定单个 Stage 的起始日期。

        优先使用指定的 start_date；否则查询该 data_type 下所有标的的最大水位日期。
        无水位返回 None（该 Stage 将被跳过）。
        """
        if start_date_str:
            return date.fromisoformat(start_date_str)

        rows = await CollectWatermark.filter(data_type=data_type, status="active")
        dates = [row.watermark_date for row in rows if row.watermark_date is not None]
        if dates:
            return min(dates)
        return None
