"""个股详情 API。"""

from typing import Any

from fastapi import APIRouter, Query

from xqtrader.domain.security.services.stock_detail_service import (
    StockChanlunService,
    StockDetailService,
    StockDirectoryService,
    StockFundFlowService,
    StockKlineService,
)
from xqtrader.domain.security.services.stock_diagnosis_service import StockDiagnosisService
from xqtrader.domain.security.services.stock_technical_service import (
    StockTechnicalService,
)

router = APIRouter(prefix="/stocks", tags=["个股"])

_directory_service = StockDirectoryService()
_detail_service = StockDetailService()
_kline_service = StockKlineService()
_fund_flow_service = StockFundFlowService()
_chanlun_service = StockChanlunService()
_technical_service = StockTechnicalService()
_diagnosis_service = StockDiagnosisService()


@router.get("", summary="查询股票列表")
async def list_stocks(
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    market: str | None = Query(default=None, description="市场"),
    industry: str | None = Query(default=None, description="行业"),
    list_status: str | None = Query(default="L", description="上市状态"),
    q: str | None = Query(default=None, description="搜索关键字"),
) -> dict:
    return await _directory_service.list_stocks(
        page=page,
        page_size=page_size,
        market=market,
        industry=industry,
        list_status=list_status,
        q=q,
    )


@router.get("/search", summary="搜索股票", operation_id="search_stocks")
async def search_stocks(
    q: str = Query(default="", description="股票代码、名称或拼音"),
    limit: int = Query(default=20, ge=1, le=50, description="返回数量"),
) -> list[dict]:
    return await _directory_service.search_stocks(q=q, limit=limit)


@router.get("/tags/definitions", summary="查询股票标签定义")
async def get_tag_definitions() -> list[dict]:
    return await _directory_service.get_tag_definitions()


@router.get("/tags/{symbol}", summary="查询股票标签")
async def get_stock_tags(symbol: str) -> list[dict]:
    return await _directory_service.get_stock_tags(symbol)


@router.get("/{symbol}", summary="查询个股概览", operation_id="get_stock_overview")
async def get_stock_overview(symbol: str) -> dict:
    return await _detail_service.get_overview(symbol)


@router.get("/{symbol}/kline", summary="查询个股日K及技术指标", operation_id="get_stock_kline")
async def get_stock_kline(
    symbol: str,
    limit: int = Query(default=1200, ge=100, le=12000, description="K线条数"),
) -> dict:
    return await _kline_service.get_kline(symbol=symbol, limit=limit)


@router.get("/{symbol}/kline/bars", summary="查询个股日K", operation_id="get_stock_kline_bars")
async def get_stock_kline_bars(
    symbol: str,
    limit: int = Query(default=1200, ge=100, le=12000, description="K线条数"),
) -> list[dict[str, Any]]:
    return await _kline_service.get_kline_bars(symbol=symbol, limit=limit)


@router.get("/{symbol}/technical", summary="查询个股技术面综合诊断", operation_id="get_stock_technical")
async def get_stock_technical(symbol: str) -> dict:
    return await _technical_service.get_technical(symbol)


@router.get("/{symbol}/chanlun", summary="查询缠论图形元素", operation_id="get_stock_chanlun")
async def get_stock_chanlun(symbol: str) -> dict:
    return await _chanlun_service.get_chanlun(symbol)


@router.get("/{symbol}/trend", summary="查询个股趋势诊断", operation_id="get_stock_trend")
async def get_stock_trend(
    symbol: str,
    limit: int = Query(default=120, ge=60, le=12000, description="K线条数"),
) -> dict:
    return await _technical_service.get_trend(symbol=symbol, limit=limit)


@router.get("/{symbol}/momentum", summary="查询个股动量诊断", operation_id="get_stock_momentum")
async def get_stock_momentum(
    symbol: str,
    limit: int = Query(default=120, ge=35, le=12000, description="K线条数"),
) -> dict:
    return await _technical_service.get_momentum(symbol=symbol, limit=limit)


@router.get("/{symbol}/valuation", summary="查询个股估值诊断", operation_id="get_stock_valuation")
async def get_stock_valuation(
    symbol: str,
    limit: int = Query(default=252, ge=30, le=12000, description="估值历史样本天数"),
) -> dict:
    return await _technical_service.get_valuation(symbol=symbol, limit=limit)


@router.get("/{symbol}/news", summary="查询个股资讯", operation_id="get_stock_news")
async def get_stock_news(symbol: str) -> dict:
    return await _detail_service.get_news(symbol)


@router.get("/{symbol}/announcements", summary="查询个股公告", operation_id="get_stock_announcements")
async def get_stock_announcements(symbol: str) -> dict:
    return await _detail_service.get_announcements(symbol)


@router.get("/{symbol}/financials", summary="查询个股财务摘要", operation_id="get_stock_financials")
async def get_stock_financials(symbol: str) -> dict:
    return await _detail_service.get_financials(symbol)


@router.get("/{symbol}/fund-flow", summary="查询个股资金流", operation_id="get_stock_fund_flow")
async def get_stock_fund_flow(
    symbol: str,
    limit: int = Query(default=120, ge=1, le=12000, description="返回条数"),
) -> dict:
    return await _fund_flow_service.get_fund_flow(symbol, limit=limit)


@router.get("/{symbol}/diagnosis", summary="查询个股诊股评分", operation_id="get_stock_diagnosis")
async def get_stock_diagnosis(
    symbol: str,
    refresh: bool = Query(default=False, description="强制重算评分（忽略当日快照）"),
) -> dict:
    return await _diagnosis_service.get_diagnosis(symbol, refresh=refresh)


@router.get(
    "/{symbol}/diagnosis/history",
    summary="查询个股诊股得分走势",
    operation_id="get_stock_diagnosis_history",
)
async def get_stock_diagnosis_history(
    symbol: str,
    days: int = Query(default=90, ge=7, le=365, description="回溯天数"),
) -> dict:
    return await _diagnosis_service.get_history(symbol, days=days)


@router.post(
    "/{symbol}/diagnosis/summary",
    summary="异步生成诊股 AI 解读",
    operation_id="trigger_stock_diagnosis_summary",
)
async def trigger_stock_diagnosis_summary(symbol: str) -> dict:
    from worker.celery_app import celery_app

    result = celery_app.send_task(
        "market.stock_diagnosis_summary",
        kwargs={"symbol": symbol},
    )
    return {
        "symbol": symbol,
        "task_id": result.id,
        "status": "PENDING",
    }
