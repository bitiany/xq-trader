from fastapi import APIRouter, Query

from framework.commons.exceptions import NotFoundException
from xqtrader.domain.security.services.security_service import SecurityService

router = APIRouter(prefix="/securities", tags=["证券"])

_service = SecurityService()


@router.get("", summary="查询证券列表")
async def list_securities(
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    industry: str | None = Query(default=None, description="行业过滤"),
) -> dict:
    return await _service.list_securities(page=page, page_size=page_size, industry=industry)


@router.get("/{symbol}", summary="查询证券详情")
async def get_security(symbol: str) -> dict:
    security = await _service.get_by_symbol(symbol)
    if security is None:
        raise NotFoundException(message=f"证券 {symbol} 不存在")
    return security
