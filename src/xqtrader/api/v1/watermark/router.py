from datetime import date

from fastapi import APIRouter, Query

from xqtrader.domain.watermark.models.trade_calendar import DEFAULT_TRADE_EXCHANGE, TradeCalendar
from xqtrader.domain.watermark.services.watermark_service import WatermarkService

router = APIRouter(prefix="/watermarks", tags=["水位"])

_service = WatermarkService()


@router.get("/trade-calendar/latest", summary="查询最近交易日")
async def get_latest_trade_date(
    exchange: str = Query(default=DEFAULT_TRADE_EXCHANGE, description="交易所代码：SSE/SZSE/BSE"),
    on_or_before: date | None = Query(default=None, description="查询该日期及之前最近交易日"),
) -> dict:
    """返回交易日历中 on_or_before 当日及之前最近的一个交易日。"""
    latest = await TradeCalendar.get_latest_trade_date(
        exchange=exchange,
        on_or_before=on_or_before,
    )
    return {
        "exchange": exchange,
        "latest_trade_date": str(latest) if latest else None,
    }


@router.get("/incremental-start", summary="计算增量采集起始日期")
async def get_incremental_start_date(
    data_type: str = Query(..., description="数据类型，如daily_kline"),
    watermark_code: str = Query(..., description="水位标识代码"),
) -> dict:
    """根据水位和交易日历计算增量采集的起始日期。

    返回:
    - start_date: 水位日期（需增量采集）或 null（水位已最新）
    - latest_trade_date: 最新交易日
    """
    start_date = await _service.get_incremental_start_date(data_type, watermark_code)
    latest_trade_date = await _service.get_latest_trade_date()

    return {
        "data_type": data_type,
        "watermark_code": watermark_code,
        "start_date": str(start_date) if start_date else None,
        "latest_trade_date": str(latest_trade_date) if latest_trade_date else None,
    }


@router.get("/incremental-start/batch", summary="批量计算增量采集起始日期")
async def get_incremental_start_dates(
    data_type: str = Query(..., description="数据类型，如daily_kline"),
) -> dict:
    """批量计算某数据类型下所有水位标识的增量起始日期。"""
    result = await _service.get_incremental_start_dates(data_type)
    return {
        "data_type": data_type,
        "items": {code: str(d) if d else None for code, d in result.items()},
    }
