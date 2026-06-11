"""水位切面 — 前切获取水位日期作为增量起始时间，后切更新水位。

所有需要增量采集的插件均可复用此切面，通过 pipeline_name 区分不同管线的水位。

前切逻辑：
  1. 若上下文中已有 collect_date（外部指定采集日期），则使用该日期作为起始时间
  2. 否则查询 CollectWatermark 获取水位日期作为增量起始时间
  3. 水位最新时标记 is_up_to_date，跳过后续 Stage

后切逻辑：
  1. 持久化成功后，更新水位日期为参考日期（当前或前一交易日）
"""

from __future__ import annotations

from typing import Any

from framework.commons.logger import get_logger
from framework.pipeline import Aspect, PipelineContext, PipelineError, StageResult
from xqtrader.domain.watermark.models.collect_watermark import CollectWatermark
from xqtrader.domain.watermark.services.watermark_service import WatermarkService

logger = get_logger(__name__)


class WatermarkAspect(Aspect):
    """水位切面 — 前切获取水位日期作为增量起始时间，后切更新水位。"""

    def __init__(self, pipeline_name: str = "daily_kline") -> None:
        self._pipeline_name = pipeline_name
        self._watermark_service = WatermarkService()

    @property
    def name(self) -> str:
        return "watermark"

    async def before(self, item: Any, ctx: PipelineContext) -> None:
        """前切：获取增量采集起始时间。

        优先使用上下文中的 collect_date（外部指定采集日期），
        否则查询水位日期作为增量起始时间。
        """
        stock_code: str = item

        # 优先使用外部指定的采集日期
        collect_date = ctx.get("collect_date")
        if collect_date:
            ctx.set("start_date", str(collect_date))
            ctx.set("is_up_to_date", False)
            ctx.set("end_date", "")
            logger.debug("指定采集日期: %s start=%s", stock_code, collect_date)
            return

        # 查询水位日期
        start_date = await self._watermark_service.get_incremental_start_date(
            pipeline_name=self._pipeline_name,
            watermark_code=stock_code,
        )
        if start_date is None:
            ctx.set("start_date", "")
            ctx.set("is_up_to_date", True)
            logger.debug("水位最新，跳过: %s", stock_code)
        else:
            ctx.set("start_date", str(start_date))
            ctx.set("is_up_to_date", False)
            ctx.set("end_date", "")

    async def after(self, item: Any, ctx: PipelineContext, result: StageResult) -> None:
        """后切：持久化成功后更新水位日期（使用 bulk_create_or_update）。

        注意：record_count 仅在首次创建时设置，更新时不累加。
        """
        if not result.success:
            return

        stock_code: str = item
        persisted = ctx.get("persisted_count", 0)
        if persisted == 0:
            return

        try:
            ref_date = self._watermark_service.get_reference_date()
            instance = CollectWatermark(
                pipeline_name=self._pipeline_name,
                watermark_code=stock_code,
                watermark_date=ref_date,
                record_count=persisted,
                status="active",
            )
            await CollectWatermark.bulk_create_or_update(
                [instance],
                on_conflict=["pipeline_name", "watermark_code"],
                update_fields=["watermark_date"],
            )
            logger.debug("水位更新: %s → %s", stock_code, ref_date)
        except Exception as e:
            raise PipelineError(f"水位更新失败 {stock_code}: {e}") from e

    async def on_error(self, item: Any, ctx: PipelineContext, error: Exception) -> None:
        """错误钩子：记录失败日志。"""
        logger.warning("采集失败: %s, error=%s", item, error)
