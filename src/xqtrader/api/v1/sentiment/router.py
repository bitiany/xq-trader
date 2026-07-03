"""舆情快照 API — 提供市场级与个股级舆情查询。"""

from fastapi import APIRouter, Query

from xqtrader.domain.research.services.sentiment_service import (
    SentimentService,
)

router = APIRouter(prefix="/sentiment", tags=["舆情"])

_service = SentimentService()


@router.get("/market", summary="查询市场舆情快照", operation_id="get_market_sentiment")
async def get_market_sentiment(
    days: int = Query(default=7, ge=1, le=90, description="返回最近 N 天的舆情"),
) -> dict:
    return await _service.get_market_sentiment(days=days)


@router.get("/stocks/{symbol}", summary="查询个股舆情快照", operation_id="get_stock_sentiment")
async def get_stock_sentiment(
    symbol: str,
    days: int = Query(default=7, ge=1, le=90, description="返回最近 N 天的舆情"),
) -> dict:
    return await _service.get_stock_sentiment(symbol=symbol, days=days)
