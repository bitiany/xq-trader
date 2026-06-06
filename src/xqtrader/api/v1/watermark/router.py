from fastapi import APIRouter, Query

from xqtrader.domain.watermark.models.trade_calendar import TradeCalendar
from xqtrader.domain.watermark.services.watermark_service import WatermarkService

router = APIRouter(prefix="/watermarks", tags=["水位"])

_service = WatermarkService()


@router.get("/incremental-start", summary="计算增量采集起始日期")
async def get_incremental_start_date(
    pipeline_name: str = Query(..., description="Pipeline名称"),
    watermark_code: str = Query(..., description="水位标识代码"),
) -> dict:
    """根据水位和交易日历计算增量采集的起始日期。

    返回:
    - start_date: 水位日期（需增量采集）或 null（水位已最新）
    - latest_trade_date: 最新交易日
    """
    start_date = await _service.get_incremental_start_date(pipeline_name, watermark_code)
    ref_date = _service._get_reference_date()
    latest_trade_date = await TradeCalendar.get_latest_trade_date(on_or_before=ref_date)

    return {
        "pipeline_name": pipeline_name,
        "watermark_code": watermark_code,
        "start_date": str(start_date) if start_date else None,
        "latest_trade_date": str(latest_trade_date) if latest_trade_date else None,
    }


@router.get("/incremental-start/batch", summary="批量计算增量采集起始日期")
async def get_incremental_start_dates(
    pipeline_name: str = Query(..., description="Pipeline名称"),
) -> dict:
    """批量计算某 Pipeline 下所有水位标识的增量起始日期。"""
    result = await _service.get_incremental_start_dates(pipeline_name)
    return {
        "pipeline_name": pipeline_name,
        "items": {code: str(d) if d else None for code, d in result.items()},
    }
