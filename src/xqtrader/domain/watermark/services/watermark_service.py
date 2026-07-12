"""水位服务 — 根据交易日历和采集水位计算增量采集的起始日期。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from framework.commons.logger import get_logger
from xqtrader.domain.watermark.models.collect_watermark import CollectWatermark
from xqtrader.domain.watermark.models.trade_calendar import DEFAULT_TRADE_EXCHANGE, TradeCalendar

logger = get_logger(__name__)


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
        data_type: str,
        watermark_code: str,
        default_start_date: date | None = None,
    ) -> date | None:
        """计算增量采集的起始日期。

        Args:
            data_type: 数据类型，如 "daily_kline"
            watermark_code: 水位标识代码，如 "000001.SZ"
            default_start_date: 水位为空时的默认起始日期，None 则使用 1990-01-01

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
            data_type=data_type,
            watermark_code=watermark_code,
        )
        watermark_date = watermark.watermark_date if watermark else None

        if watermark_date is None:
            fallback = default_start_date or date(1990, 1, 1)
            logger.debug(
                "水位为空，需全量采集: data_type=%s code=%s start=%s",
                data_type, watermark_code, fallback,
            )
            return fallback

        if watermark_date >= latest_trade_date:
            logger.debug(
                "水位已是最新: data_type=%s code=%s watermark=%s trade_date=%s",
                data_type, watermark_code, watermark_date, latest_trade_date,
            )
            return None

        logger.debug(
            "水位落后，需增量采集: data_type=%s code=%s watermark=%s trade_date=%s",
            data_type, watermark_code, watermark_date, latest_trade_date,
        )
        return watermark_date

    async def get_incremental_start_dates(
        self,
        data_type: str,
    ) -> dict[str, date | None]:
        """批量计算某数据类型下所有水位标识的增量起始日期。

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
            data_type=data_type,
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
