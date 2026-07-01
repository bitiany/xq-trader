"""指数行情 API — 提供指数列表、概览与K线查询。"""

from fastapi import APIRouter, Query

from xqtrader.domain.index.services import IndexKlineService, IndexService

router = APIRouter(prefix="/indices", tags=["指数"])

_index_service = IndexService()
_index_kline_service = IndexKlineService()


@router.get("", summary="查询指数列表", operation_id="list_indices")
async def list_indices(
    keyword: str | None = Query(default=None, description="名称关键字"),
    index_type: str | None = Query(default=None, description="指数类型"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
) -> dict:
    return await _index_service.list_indices(
        keyword=keyword, index_type=index_type, page=page, page_size=page_size,
    )


@router.get("/{symbol}", summary="查询指数概览", operation_id="get_index_overview")
async def get_index_overview(symbol: str) -> dict:
    return await _index_service.get_overview(symbol)


@router.get("/{symbol}/kline", summary="查询指数日K及技术指标", operation_id="get_index_kline")
async def get_index_kline(
    symbol: str,
    limit: int = Query(default=1200, ge=100, le=12000, description="K线条数"),
) -> dict:
    return await _index_kline_service.get_kline(symbol=symbol, limit=limit)
