"""券商研报 API — 提供个股研报列表与详情查询。"""

from fastapi import APIRouter, Query

from xqtrader.domain.research.services.research_report_service import (
    ResearchReportService,
)

router = APIRouter(prefix="/research", tags=["研报"])

_service = ResearchReportService()


@router.get("/reports", summary="查询个股研报列表", operation_id="list_stock_research_reports")
async def list_stock_research_reports(
    symbol: str = Query(..., description="标的代码，如 002049.SZ"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
) -> dict:
    return await _service.list_reports(symbol=symbol, page=page, page_size=page_size)


@router.get("/reports/{info_code}", summary="查询研报详情", operation_id="get_research_report")
async def get_research_report(info_code: str) -> dict:
    return await _service.get_report(info_code)
