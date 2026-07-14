"""水位切面 — 前切获取水位日期作为增量起始时间，后切更新水位。

所有需要增量采集的插件均可复用此切面，通过 data_type 区分不同数据类型的水位。

前切逻辑：
  1. 若上下文中已有 collect_date（外部指定采集日期），则使用该日期作为起始时间
  2. 否则查询 CollectWatermark 获取水位日期作为增量起始时间
  3. 水位最新时标记 is_up_to_date，跳过后续 Stage
  4. 设置 end_date 为最新交易日（缓存避免重复查询）

后切逻辑：
  1. 持久化成功后，更新水位日期为参考日期（当前或前一交易日）
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from framework.commons.logger import get_logger
from framework.pipeline import Aspect, PipelineContext, PipelineError, StageResult
from xqtrader.domain.watermark.models.collect_watermark import CollectWatermark
from xqtrader.domain.watermark.services.watermark_service import WatermarkService

logger = get_logger(__name__)


class WatermarkAspect(Aspect):
    """水位切面 — 前切获取水位日期作为增量起始时间，后切更新水位。"""

    def __init__(
        self,
        data_type: str = "daily_kline",
        default_start_date: date | None = None,
    ) -> None:
        self._data_type = data_type
        self._default_start_date = default_start_date
        self._watermark_service = WatermarkService()
        self._latest_trade_date: date | None = None

    @property
    def name(self) -> str:
        return "watermark"

    async def _get_latest_trade_date(self) -> date | None:
        """获取最新交易日（缓存避免重复查询数据库）。"""
        if self._latest_trade_date is None:
            self._latest_trade_date = await self._watermark_service.get_latest_trade_date()
        return self._latest_trade_date

    async def before(self, item: Any, ctx: PipelineContext) -> None:
        """前切：获取增量采集起始时间。

        优先使用上下文中的 collect_date（外部指定采集日期），
        否则查询水位日期作为增量起始时间。
        水位最新时标记 is_up_to_date 跳过后续 Stage。
        设置 end_date 为最新交易日，避免下载范围超出当前时间。
        """
        stock_code: str = item

        # 优先使用外部指定的采集日期（绕过水位检查）
        collect_date = ctx.get("collect_date")
        if collect_date:
            start_str = self._normalize_date_str(str(collect_date))
            ctx.set("start_date", start_str)
            ctx.set("is_up_to_date", False)
            latest = await self._get_latest_trade_date()
            ctx.set("end_date", latest.strftime("%Y%m%d") if latest else "")
            logger.debug("[watermark] 指定采集日期: %s start=%s end=%s", stock_code, start_str, latest)
            return

        # 查询水位日期
        start_date = await self._watermark_service.get_incremental_start_date(
            data_type=self._data_type,
            watermark_code=stock_code,
            default_start_date=self._default_start_date,
        )
        if start_date is None:
            ctx.set("start_date", "")
            ctx.set("is_up_to_date", True)
            ctx.set("end_date", "")
            logger.debug("[watermark] 水位最新，跳过: %s", stock_code)
        else:
            latest = await self._get_latest_trade_date()
            ctx.set("start_date", str(start_date).replace("-", ""))
            ctx.set("is_up_to_date", False)
            ctx.set("end_date", latest.strftime("%Y%m%d") if latest else "")

    async def after(self, item: Any, ctx: PipelineContext, result: StageResult) -> None:
        """后切：持久化成功后按数据实际最新日期更新水位。

        优先使用 PersistStage 设置的 max_ann_date / max_trade_date（数据实际最新日期），
        若无则回退到参考日期（当前或前一交易日）。
        """
        if not result.success:
            return

        stock_code: str = item
        persisted = ctx.get("persisted_count", 0)
        if persisted == 0:
            return

        try:
            # 仅在有数据实际最新日期时更新水位
            # 季频财务插件使用 max_ann_date（公告日期），日频插件使用 max_trade_date（交易日）
            watermark_date = ctx.get("max_ann_date") or ctx.get("max_trade_date")
            if watermark_date is None:
                return

            instance = CollectWatermark(
                data_type=self._data_type,
                watermark_code=stock_code,
                watermark_date=watermark_date,
                record_count=0,
                status="active",
                updated_at=datetime.now(),
            )
            await CollectWatermark.bulk_create_or_update(
                [instance],
                on_conflict=["data_type", "watermark_code"],
                update_fields=["watermark_date", "status", "updated_at"],
            )
            logger.debug("水位更新: %s → %s", stock_code, watermark_date)
        except Exception as e:
            raise PipelineError(f"水位更新失败 {stock_code}: {e}") from e

    async def on_error(self, item: Any, ctx: PipelineContext, error: Exception) -> None:
        """错误钩子：记录失败日志。"""
        logger.warning("采集失败: %s, error=%s", item, error)

    @staticmethod
    def _normalize_date_str(date_str: str) -> str:
        """将日期字符串统一转换为 YYYYMMDD 格式（去除连字符）。

        支持输入格式：YYYY-MM-DD、YYYYMMDD、date 对象的 str 表示。
        """
        return date_str.replace("-", "")
