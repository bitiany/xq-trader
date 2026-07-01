"""全市场个股日频增量采集任务（日 K 线 / 资金流向 / 每日指标）。

按日期增量采集全市场个股日行情K线、资金流向、每日指标，
每个 Stage 独立完成采集→清洗→持久化→更新水位闭环。

指数（market.index_daily_collect）与申万行业（market.sw_daily_collect）
为独立插件任务；日频统一编排在 schedules/daily_pipeline.yml，仅执行顺序、无数据依赖。
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
from xqtrader.domain.security.models import Security
from xqtrader.domain.watermark.models.collect_watermark import CollectWatermark

logger = get_logger(__name__)


class DailyIncrementalTask(BaseTask):
    """全市场个股日频增量采集（日 K 线 + 资金流向 + 每日指标）。

    入参：
      - start_date: 采集起始日期（格式 YYYY-MM-DD，为空时按各 Stage 标的级水位）
      - kline_batch_size: QMT 标的分片大小（默认 500）
    """
    task_name = "market.daily_incremental_collect"

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        start_date_str: str | None = kwargs.get("start_date")
        kline_batch_size: int = kwargs.get("kline_batch_size", 500)

        end_date = date.today()

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

        all_no_watermark = (
            kline_start is None
            and ff_start is None
            and indicator_start is None
        )
        if all_no_watermark:
            return {
                "status": "ERROR",
                "message": (
                    "无水位记录，请先执行全量回补任务"
                    "（daily_kline / fund_flow / daily_indicator）"
                ),
            }

        results: dict[str, Any] = {"status": "SUCCESS", "end_date": str(end_date)}

        if kline_start is not None and kline_start < end_date:
            logger.info(
                "[daily.incremental] 日行情增量: %s~%s", kline_start, end_date,
            )
            kline_stage = DailyKlineIncrementalStage(batch_size=kline_batch_size)
            results["daily_kline"] = await kline_stage.execute(kline_start, end_date)
        else:
            logger.info("[daily.incremental] 日行情: 无水位或已最新，跳过")
            results["daily_kline"] = {"status": "SKIPPED"}

        if ff_start is not None and ff_start < end_date:
            logger.info(
                "[daily.incremental] 资金流向增量: %s~%s", ff_start, end_date,
            )
            fund_flow_stage = FundFlowIncrementalStage()
            results["fund_flow"] = await fund_flow_stage.execute(ff_start, end_date)
        else:
            logger.info("[daily.incremental] 资金流向: 无水位或已最新，跳过")
            results["fund_flow"] = {"status": "SKIPPED"}

        if indicator_start is not None and indicator_start < end_date:
            logger.info(
                "[daily.incremental] 每日指标增量: %s~%s", indicator_start, end_date,
            )
            indicator_stage = DailyIndicatorIncrementalStage()
            results["daily_indicator"] = await indicator_stage.execute(indicator_start, end_date)
        else:
            logger.info("[daily.incremental] 每日指标: 无水位或已最新，跳过")
            results["daily_indicator"] = {"status": "SKIPPED"}

        logger.info("[daily.incremental] 全部完成: %s", results)
        return results

    @staticmethod
    async def _resolve_stage_start(
        data_type: str,
        start_date_str: str | None,
    ) -> date | None:
        """确定单个 Stage 的起始日期（仅适用于上市证券类 data_type）。"""
        if start_date_str:
            return date.fromisoformat(start_date_str)

        listed = await Security.filter(list_status="L")
        listed_codes = {s.symbol for s in listed}

        rows = await CollectWatermark.filter(data_type=data_type, status="active")
        dates = [
            row.watermark_date for row in rows
            if row.watermark_date is not None and row.watermark_code in listed_codes
        ]
        if dates:
            return min(dates)
        return None
