"""因子查询 API — 因子注册表 / 因子值 / 统计指标 / 样本池。"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import desc

from framework.commons.exceptions import NotFoundException
from framework.commons.pagination import build_paginated_response, paginate
from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry
from xqtrader.domain.factor.models.factor_stats import FacFactorStats
from xqtrader.domain.factor.models.factor_value import FacFactorValue
from xqtrader.domain.factor.services.factor_series_service import FactorSeriesService

router = APIRouter(prefix="/factors", tags=["因子查询"])

_factor_series_service = FactorSeriesService()


# ==================== 因子注册表 ====================

@router.get("", summary="因子列表", operation_id="list_factors")
async def list_factors(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    category: str | None = Query(default=None, description="因子分类"),
    status: str | None = Query(default=None, description="状态过滤"),
    factor_grade: str | None = Query(default=None, description="等级过滤 A/B/C/D"),
    usable_only: bool = Query(default=False, description="仅 A/B 级可用因子"),
    keyword: str | None = Query(default=None, description="按名称/ID模糊搜索"),
) -> dict:
    skip, limit = paginate(page, page_size)
    and_filters: dict = {}
    if category:
        and_filters["category"] = category
    if status:
        and_filters["status"] = status
    if factor_grade:
        and_filters["factor_grade"] = factor_grade
    if usable_only:
        and_filters["factor_grade__in"] = ["A", "B"]

    or_conditions: list | None = None
    if keyword:
        kw = f"%{keyword}%"
        or_conditions = [
            FacFactorRegistry.display_name.like(kw),
            FacFactorRegistry.factor_id.like(kw),
        ]

    if or_conditions:
        items = await FacFactorRegistry.filter_with_or(
            or_conditions=or_conditions,
            and_filters=and_filters,
            skip=skip,
            limit=limit,
            order_by=FacFactorRegistry.factor_id,
        )
        total = await FacFactorRegistry.count_with_or(
            or_conditions=or_conditions,
            and_filters=and_filters,
        )
    else:
        items = await FacFactorRegistry.filter(
            skip=skip,
            limit=limit,
            order_by=FacFactorRegistry.factor_id,
            **and_filters,
        )
        total = await FacFactorRegistry.count(**and_filters)

    return build_paginated_response(
        [f.to_dict() for f in items], total, page, page_size,
    )


@router.get("/categories", summary="因子分类聚合", operation_id="list_factor_categories")
async def list_categories() -> list[dict]:
    """按 category 聚合统计，供前端筛选 chip 使用。"""
    items = await FacFactorRegistry.filter(limit=0)
    bucket: dict[str, int] = {}
    for f in items:
        bucket[f.category] = bucket.get(f.category, 0) + 1
    return [{"category": k, "count": v} for k, v in sorted(bucket.items())]


@router.get(
    "/series/{symbol}",
    summary="个股因子宽表时序（平台全部活跃因子）",
    operation_id="get_stock_factor_series",
)
async def get_stock_factor_series(
    symbol: str,
    start_date: date | None = Query(default=None, description="起始日期（默认近120交易日）"),
    end_date: date | None = Query(default=None, description="结束日期（默认今天）"),
    pool_id: str = Query(default="all", description="样本池"),
    days: int | None = Query(default=None, ge=1, le=60, description="近N个自然日（优先于 start_date）"),
) -> dict:
    """返回平台全部 active 因子元数据 + 单标的按 trade_date 宽字段时序 rows。"""
    if days is not None:
        end = end_date or date.today()
        start = end - timedelta(days=days)
        return await _factor_series_service.get_stock_factor_series(
            symbol,
            start_date=start,
            end_date=end,
            pool_id=pool_id,
        )
    return await _factor_series_service.get_stock_factor_series(
        symbol,
        start_date=start_date,
        end_date=end_date,
        pool_id=pool_id,
    )


@router.get("/{factor_id}", summary="因子详情", operation_id="get_factor")
async def get_factor(factor_id: str) -> dict:
    f = await FacFactorRegistry.get_or_none(factor_id=factor_id)
    if f is None:
        raise NotFoundException(message=f"因子不存在: {factor_id}")
    return f.to_dict()


# ==================== 因子值（截面） ====================

@router.get("/{factor_id}/values", summary="因子值查询（截面）", operation_id="get_factor_values")
async def list_factor_values(
    factor_id: str,
    trade_date: date = Query(..., description="交易日期"),
    pool_id: str = Query(default="all", description="样本池"),
    symbols: str | None = Query(default=None, description="符号列表（逗号分隔）"),
    limit: int = Query(default=200, ge=1, le=2000),
) -> list[dict]:
    """返回指定 factor_id × trade_date × pool_id 的截面因子值。"""
    filters: dict = {
        "factor_id": factor_id,
        "trade_date": trade_date,
        "pool_id": pool_id,
    }
    if symbols:
        filters["symbol__in"] = [s.strip() for s in symbols.split(",") if s.strip()]

    rows = await FacFactorValue.filter(limit=limit, **filters)
    return [
        {
            "symbol": r.symbol,
            "trade_date": str(r.trade_date),
            "factor_id": r.factor_id,
            "pool_id": r.pool_id,
            "factor_value": r.factor_value,
        }
        for r in rows
    ]


# ==================== 因子评估统计 ====================

@router.get("/{factor_id}/stats", summary="因子评估统计")
async def get_factor_stats(
    factor_id: str,
    pool_id: str = Query(default="all", description="样本池"),
    start_date: date | None = Query(default=None, description="开始日期"),
    end_date: date | None = Query(default=None, description="结束日期"),
    limit: int = Query(default=252, ge=1, le=2000),
) -> list[dict]:
    """返回因子的 IC/ICIR 时间序列统计。"""
    filters: dict = {"factor_id": factor_id, "pool_id": pool_id}
    if start_date is not None:
        filters["calc_date__gte"] = start_date
    if end_date is not None:
        filters["calc_date__lte"] = end_date

    rows = await FacFactorStats.filter(
        order_by=desc(FacFactorStats.calc_date),
        limit=limit,
        **filters,
    )
    return [r.to_dict() for r in rows]


@router.get("/{factor_id}/stats/latest", summary="因子最新评估快照", operation_id="get_factor_stats_latest")
async def get_factor_stats_latest(
    factor_id: str,
    pool_id: str = Query(default="all", description="样本池"),
) -> dict | None:
    """返回因子最近一期的统计快照（IC/ICIR/胜率/分层等）。"""
    rows = await FacFactorStats.filter(
        factor_id=factor_id,
        pool_id=pool_id,
        order_by=desc(FacFactorStats.calc_date),
        limit=1,
    )
    return rows[0].to_dict() if rows else None
