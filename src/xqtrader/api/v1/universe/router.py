"""样本池 API — 样本池配置 + 指数成分股查询。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from framework.commons.pagination import build_paginated_response, paginate
from xqtrader.domain.factor.models.factor_pool import FacFactorPool
from xqtrader.domain.factor.services.cross_section_reader import CrossSectionReader
from xqtrader.domain.security.models import Security

router = APIRouter(prefix="/universe", tags=["样本池"])

# 选股工作台支持的样本池（与 trading.rules.base.UniverseProvider 子类对齐）
_BUILTIN_POOLS = [
    {"pool_id": "all", "pool_name": "全市场", "pool_type": "all"},
    {"pool_id": "idx_50", "pool_name": "上证50", "pool_type": "index"},
    {"pool_id": "idx_300", "pool_name": "沪深300", "pool_type": "index"},
    {"pool_id": "idx_500", "pool_name": "中证500", "pool_type": "index"},
    {"pool_id": "idx_800", "pool_name": "中证800", "pool_type": "index"},
    {"pool_id": "idx_1000", "pool_name": "中证1000", "pool_type": "index"},
]


@router.get("/pools", summary="样本池列表")
async def list_pools(include_db: bool = Query(default=True, description="是否合并数据库样本池")) -> list[dict]:
    """返回内置样本池 + 数据库注册的样本池。"""
    out: list[dict] = list(_BUILTIN_POOLS)
    if include_db:
        rows = await FacFactorPool.filter(status="active")
        existing_ids = {p["pool_id"] for p in out}
        for r in rows:
            if r.pool_id in existing_ids:
                continue
            out.append({
                "pool_id": r.pool_id,
                "pool_name": r.pool_name,
                "pool_type": r.pool_type,
                "definition": r.definition,
            })
    return out


@router.get("/pools/{pool_id}/symbols", summary="样本池标的列表")
async def list_pool_symbols(
    pool_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    keyword: str | None = Query(default=None, description="按名称/代码模糊搜索"),
) -> dict:
    """返回样本池下的标的列表（含证券名称、行业），支持分页与关键字过滤。"""
    reader = CrossSectionReader()
    all_symbols = await reader.load_pool_symbols(pool_id)
    if not all_symbols:
        return build_paginated_response([], 0, page, page_size)

    # 加载证券基本信息
    secs = await Security.filter(symbol__in=all_symbols)
    sec_list = [s.to_dict() for s in secs]

    # 关键字过滤
    if keyword:
        kw = keyword.lower()
        sec_list = [
            s for s in sec_list
            if kw in (s.get("symbol") or "").lower()
            or kw in (s.get("name") or "").lower()
            or kw in (s.get("cnspell") or "").lower()
        ]

    sec_list.sort(key=lambda x: x.get("symbol") or "")
    total = len(sec_list)
    skip, limit = paginate(page, page_size)
    paged = sec_list[skip: skip + limit]
    return build_paginated_response(paged, total, page, page_size)
