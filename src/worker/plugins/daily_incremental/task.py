"""日行情与资金流向增量采集任务。

按日期增量采集全市场日行情K线和资金流向数据，每个数据类型独立完成
采集→清洗→持久化→更新水位闭环。

水位策略：
  - 市场级水位（pipeline_name=daily_kline_incremental/fund_flow_incremental,
    watermark_code=MARKET）确定增量日期范围
  - 无市场水位 → 报错，提示先执行全量回补任务
  - 标的级水位（与回补任务共享）用于过滤已采集数据，采集后按标的更新
"""

from __future__ import annotations

from datetime import date
from typing import Any

from framework.commons.logger import get_logger
from framework.scheduler.base_task import BaseTask
from worker.plugins.daily_incremental.stages.daily_kline_stage import (
    DailyKlineIncrementalStage,
)
from worker.plugins.daily_incremental.stages.fund_flow_stage import (
    FundFlowIncrementalStage,
)
from xqtrader.domain.watermark.models.collect_watermark import CollectWatermark
from xqtrader.domain.watermark.services.watermark_service import WatermarkService

logger = get_logger(__name__)


class DailyIncrementalTask(BaseTask):
    """日行情与资金流向增量采集任务。

    入参：
      - start_date: 采集起始日期（格式 YYYY-MM-DD，为空时按市场水位日期）
      - end_date: 采集结束日期（格式 YYYY-MM-DD，为空时取最新交易日）
      - kline_batch_size: QMT 标的分片大小（默认 50）
    """

    task_name = "market.daily_incremental_collect"
    description = "按日期增量采集全市场日行情K线和资金流向数据"
    time_limit = 7200
    soft_time_limit = 7170

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        start_date_str: str | None = kwargs.get("start_date")
        end_date_str: str | None = kwargs.get("end_date")
        kline_batch_size: int = kwargs.get("kline_batch_size", 50)

        # 确定日期范围
        start_date, end_date = await self._resolve_date_range(start_date_str, end_date_str)

        if start_date is None:
            return {
                "status": "ERROR",
                "message": "无市场水位记录，请先执行全量回补任务（daily_kline_collect / fund_flow_collect）",
            }

        if start_date >= end_date:
            logger.info("[daily.incremental] 数据已是最新: start=%s end=%s", start_date, end_date)
            return {"status": "UP_TO_DATE", "start_date": str(start_date), "end_date": str(end_date)}

        logger.info(
            "[daily.incremental] 开始增量采集: range=%s~%s kline_batch=%d",
            start_date, end_date, kline_batch_size,
        )

        # Stage 1: 日行情增量
        kline_stage = DailyKlineIncrementalStage(batch_size=kline_batch_size)
        kline_result = await kline_stage.execute(start_date, end_date)

        # Stage 2: 资金流向增量
        fund_flow_stage = FundFlowIncrementalStage()
        fund_flow_result = await fund_flow_stage.execute(start_date, end_date)

        result = {
            "status": "SUCCESS",
            "start_date": str(start_date),
            "end_date": str(end_date),
            "daily_kline": kline_result,
            "fund_flow": fund_flow_result,
        }

        logger.info(
            "[daily.incremental] 完成: kline_persisted=%d fund_flow_persisted=%d",
            kline_result.get("persisted", 0),
            fund_flow_result.get("persisted", 0),
        )

        return result

    async def _resolve_date_range(
        self,
        start_date_str: str | None,
        end_date_str: str | None,
    ) -> tuple[date | None, date]:
        """确定增量采集的日期范围。

        Returns:
            (start_date, end_date)
            - start_date 为 None 表示无市场水位，需先执行全量回补
            - end_date 为最新交易日
        """
        # end_date: 指定或取最新交易日
        if end_date_str:
            end_date = date.fromisoformat(end_date_str)
        else:
            ws = WatermarkService()
            latest = await ws.get_latest_trade_date()
            if latest is None:
                logger.warning("[daily.incremental] 未找到最新交易日")
                end_date = date.today()
            else:
                end_date = latest

        # start_date: 指定或取两个市场级水位的较早者
        start_date: date | None
        if start_date_str:
            start_date = date.fromisoformat(start_date_str)
        else:
            start_date = await self._get_market_watermark_start()

        return start_date, end_date

    @staticmethod
    async def _get_market_watermark_start() -> date | None:
        """获取市场级水位中的最早日期作为增量起始。

        两个市场级水位取较早者，确保两个 Stage 都有数据可采。
        任一水位不存在则返回 None（需先执行全量回补）。
        """
        kline_wm = await CollectWatermark.get_one_or_none(
            pipeline_name=DailyKlineIncrementalStage.PIPELINE_NAME,
            watermark_code=DailyKlineIncrementalStage.MARKET_WATERMARK_CODE,
        )
        fund_flow_wm = await CollectWatermark.get_one_or_none(
            pipeline_name=FundFlowIncrementalStage.PIPELINE_NAME,
            watermark_code=FundFlowIncrementalStage.MARKET_WATERMARK_CODE,
        )

        kline_date = kline_wm.watermark_date if kline_wm and kline_wm.watermark_date else None
        ff_date = fund_flow_wm.watermark_date if fund_flow_wm and fund_flow_wm.watermark_date else None

        if kline_date is None or ff_date is None:
            return None

        return min(kline_date, ff_date)
