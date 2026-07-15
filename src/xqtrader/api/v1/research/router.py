"""券商研报 API — 提供个股研报列表、详情查询与全文 RAG 检索。"""

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from xqtrader.domain.research.services.research_report_chunk_service import (
    ResearchReportChunkService,
)
from xqtrader.domain.research.services.research_report_service import (
    ResearchReportService,
)

router = APIRouter(prefix="/research", tags=["研报"])

_service = ResearchReportService()
_chunk_service = ResearchReportChunkService()


class RagQueryRequest(BaseModel):
    """研报全文 RAG 检索请求。"""

    query: str = Field(..., description="检索查询文本")
    symbol: str | None = Field(default=None, description="可选标的过滤，如 002049.SZ")
    top_k: int = Field(default=5, ge=1, le=20, description="返回条数")


class IndexRequest(BaseModel):
    """研报向量化索引触发请求。"""

    info_code: str | None = Field(
        default=None,
        description="指定研报 info_code（单条索引）；留空则批量索引待处理研报",
    )
    limit: int = Field(default=50, ge=1, le=200, description="批量索引上限（仅 info_code 为空时生效）")


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


@router.post(
    "/rag-query",
    summary="研报全文 RAG 检索（向量检索匹配 chunks）",
    operation_id="query_research_report_rag",
)
async def query_research_report_rag(req: RagQueryRequest) -> dict:
    """研报全文 RAG 检索 — 向量检索匹配研报 chunks。

    返回匹配的 chunk 文本 + 元数据（来源/发布日期/评级/相似度评分）。
    """
    results = await _chunk_service.search_chunks(
        query=req.query,
        symbol=req.symbol,
        top_k=req.top_k,
    )
    return {"query": req.query, "results": results, "count": len(results)}


@router.post(
    "/rag-index",
    summary="触发研报向量化索引",
    operation_id="index_research_reports",
)
async def index_research_reports(req: IndexRequest) -> dict:
    """触发研报全文向量化索引（增量处理 vector_indexed=false 的研报）。

    - 指定 info_code：索引单条研报
    - 不指定 info_code：批量索引待处理研报（最多 limit 条）
    """
    if req.info_code:
        count = await _chunk_service.index_report(req.info_code)
        return {"info_code": req.info_code, "chunks_indexed": count}
    count = await _chunk_service.index_pending_reports(limit=req.limit)
    return {"reports_indexed": count}
