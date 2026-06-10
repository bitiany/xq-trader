"""水位服务 — 根据交易日历和采集水位计算增量采集的起始日期。"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from xqtrader.domain.watermark.models.collect_watermark import CollectWatermark
from xqtrader.domain.watermark.models.trade_calendar import DEFAULT_TRADE_EXCHANGE, TradeCalendar

logger = logging.getLogger(__name__)


class WatermarkService:
    """水位服务：计算增量采集任务的起始日期。

    核心流程：
    1. 根据当前时间确定参考日期（15:00 前取前一日，15:00 后取当日）
    2. 查询参考日期及之前最近的交易日
    3. 对比水位日期与最新交易日，水位落后则返回水位日期作为增量起始
    """

    def __init__(self, exchange: str = DEFAULT_TRADE_EXCHANGE) -> None:
        self._exchange = exchange

    async def get_incremental_start_date(
        self,
        pipeline_name: str,
        watermark_code: str,
    ) -> date | None:
        """计算增量采集的起始日期。

        Args:
            pipeline_name: Pipeline 名称，如 "daily_kline"
            watermark_code: 水位标识代码，如 "000001.SZ"

        Returns:
            - None: 水位已是最新，无需增量采集
            - date: 水位日期，作为增量采集的起始日期
        """
        ref_date = self.get_reference_date()

        latest_trade_date = await TradeCalendar.get_latest_trade_date(
            exchange=self._exchange,
            on_or_before=ref_date,
        )
        if latest_trade_date is None:
            logger.warning("未找到交易日历数据: exchange=%s ref_date=%s", self._exchange, ref_date)
            return None

        watermark = await CollectWatermark.get_one_or_none(
            pipeline_name=pipeline_name,
            watermark_code=watermark_code,
        )
        watermark_date = watermark.watermark_date if watermark else None

        if watermark_date is None:
            logger.debug(
                "水位为空，需全量采集: pipeline=%s code=%s",
                pipeline_name, watermark_code,
            )
            return date(1990, 1, 1)

        if watermark_date >= latest_trade_date:
            logger.debug(
                "水位已是最新: pipeline=%s code=%s watermark=%s trade_date=%s",
                pipeline_name, watermark_code, watermark_date, latest_trade_date,
            )
            return None

        logger.info(
            "水位落后，需增量采集: pipeline=%s code=%s watermark=%s trade_date=%s",
            pipeline_name, watermark_code, watermark_date, latest_trade_date,
        )
        return watermark_date

    async def get_incremental_start_dates(
        self,
        pipeline_name: str,
    ) -> dict[str, date | None]:
        """批量计算某 Pipeline 下所有水位标识的增量起始日期。

        Returns:
            dict[watermark_code, start_date | None]
            - None 表示水位已最新，无需增量
        """
        ref_date = self.get_reference_date()
        latest_trade_date = await TradeCalendar.get_latest_trade_date(
            exchange=self._exchange,
            on_or_before=ref_date,
        )
        if latest_trade_date is None:
            logger.warning("未找到交易日历数据: exchange=%s ref_date=%s", self._exchange, ref_date)
            return {}

        watermarks = await CollectWatermark.filter(
            pipeline_name=pipeline_name,
            status="active",
        )

        result: dict[str, date | None] = {}
        for wm in watermarks:
            if wm.watermark_date is None:
                result[wm.watermark_code] = date(1990, 1, 1)
            elif wm.watermark_date < latest_trade_date:
                result[wm.watermark_code] = wm.watermark_date
            else:
                result[wm.watermark_code] = None

        return result

    @staticmethod
    def get_reference_date(now: datetime | None = None) -> date:
        """根据当前时间确定参考日期。

        规则：15:00 前 → 前一日，15:00 及之后 → 当日。
        使用 Asia/Shanghai 时区。
        """
        tz = ZoneInfo("Asia/Shanghai")
        current = now or datetime.now(tz)
        ref_date = current.date()
        if current.hour < 15:
            ref_date = ref_date - timedelta(days=1)
        return ref_date

    async def get_latest_trade_date(self) -> date | None:
        """获取最新交易日。"""
        ref_date = self.get_reference_date()
        return await TradeCalendar.get_latest_trade_date(
            exchange=self._exchange,
            on_or_before=ref_date,
        )
