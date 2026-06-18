"""选股 API 路由 — 同步执行 SelectionEngine + 历史结果查询。"""

from __future__ import annotations

import time
from datetime import date

from fastapi import APIRouter, Query
from sqlalchemy import desc

from framework.commons.exceptions import BusinessException
from framework.commons.logger import get_logger
from framework.commons.pagination import build_paginated_response, paginate
from xqtrader.api.v1.selection.schemas import SelectionRunRequest, SelectionRunResponse
from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry
from xqtrader.domain.market.models.candlestick import CandlestickDaily
from xqtrader.domain.security.models import Security
from xqtrader.domain.trading.models.decision import SelectionResult
from xqtrader.domain.trading.models.strategy import Strategy
from xqtrader.domain.trading.rules.base import (
    CustomUniverse,
    FullMarketUniverse,
    IndexUniverse,
    UniverseProvider,
)
from xqtrader.domain.trading.selection.engine import SelectionEngine

router = APIRouter(prefix="/selection", tags=["选股"])
logger = get_logger(__name__)


def _build_universe(req: SelectionRunRequest) -> UniverseProvider:
    """根据请求参数构建 UniverseProvider。"""
    if req.universe_type == "full_market":
        return FullMarketUniverse()
    if req.universe_type == "index":
        if not req.universe_param:
            raise BusinessException(message="index 类型必须提供 universe_param (pool_id)")
        return IndexUniverse(req.universe_param)
    if req.universe_type == "custom":
        symbols = req.custom_symbols or []
        if not symbols:
            raise BusinessException(message="custom 类型必须提供 custom_symbols 列表")
        return CustomUniverse(symbols)
    raise BusinessException(message=f"不支持的 universe_type: {req.universe_type}")


@router.post("/run", summary="运行选股引擎")
async def run_selection(req: SelectionRunRequest) -> SelectionRunResponse:
    """同步执行 SelectionEngine.run，返回选股结果。

    适合中小股池（<2000 标的，秒级返回）。全市场场景请关注响应耗时。
    """
    universe = _build_universe(req)
    universe_size = len(await universe.get_symbols())

    start = time.time()
    engine = SelectionEngine()
    results = await engine.run(req.strategy_id, req.signal_date, universe)
    elapsed_ms = int((time.time() - start) * 1000)

    # 按得分倒序排列，取 Top N
    sorted_items = sorted(
        results.items(), key=lambda x: x[1].score, reverse=True,
    )[: req.top_n]

    # 加载证券名称、行业、截面行情（批量一次查询，避免前端 N 次单查）
    symbols = [s for s, _ in sorted_items]
    sec_info: dict[str, dict[str, str]] = {}
    quote_info: dict[str, dict[str, float | None]] = {}
    if symbols:
        secs = await Security.filter(symbol__in=symbols)
        sec_info = {
            s.symbol: {"name": s.name or "", "industry": s.industry or ""}
            for s in secs
        }
        quotes = await CandlestickDaily.filter(
            symbol__in=symbols,
            trade_date=req.signal_date,
        )
        quote_info = {
            q.symbol: {
                "close": float(q.close) if q.close is not None else None,
                "pct_chg": float(q.pct_chg) if q.pct_chg is not None else None,
            }
            for q in quotes
        }

    factor_ids = sorted({
        fid
        for _, score in sorted_items
        for fid in score.detail.get("factor_values", {})
    })
    factor_labels: dict[str, str] = {}
    if factor_ids:
        factors = await FacFactorRegistry.filter(factor_id__in=factor_ids)
        factor_labels = {
            f.factor_id: f.display_name or f.factor_id
            for f in factors
        }

    items = [
        {
            "rank": idx + 1,
            "symbol": symbol,
            "name": sec_info.get(symbol, {}).get("name", ""),
            "industry": sec_info.get(symbol, {}).get("industry", ""),
            "close": quote_info.get(symbol, {}).get("close"),
            "pct_chg": quote_info.get(symbol, {}).get("pct_chg"),
            "score": round(score.score, 4),
            "direction": score.direction,
            "confidence": round(score.confidence, 4),
            "factor_values": score.detail.get("factor_values", {}),
        }
        for idx, (symbol, score) in enumerate(sorted_items)
    ]

    return SelectionRunResponse(
        strategy_id=req.strategy_id,
        signal_date=req.signal_date,
        universe_type=req.universe_type,
        universe_size=universe_size,
        selected_count=len(results),
        elapsed_ms=elapsed_ms,
        items=items,
        factor_labels=factor_labels,
        filter_steps=engine.last_diagnostics.get("filter_steps", []),
    )


@router.get("/results", summary="查询历史选股结果（分页）", operation_id="list_selection_results")
async def list_selection_results(
    strategy_id: str | None = Query(default=None, description="策略编码过滤"),
    signal_date: date | None = Query(default=None, description="信号日过滤"),
    instance_id: int | None = Query(default=None, description="策略实例ID过滤"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> dict:
    """按 strategy_id / signal_date / instance_id 查询历史选股结果。

    研究域选股 instance_id=0；指定 strategy_id 时会先解析为 instance_id 集合。
    """
    skip, limit = paginate(page, page_size)

    filters: dict = {}
    if signal_date is not None:
        filters["signal_date"] = signal_date
    if instance_id is not None:
        filters["instance_id"] = instance_id
    elif strategy_id is not None:
        # strategy_id 仅在研究域有意义（instance_id=0），实例化场景需直接传 instance_id
        strategy = await Strategy.get_or_none(strategy_id=strategy_id)
        if strategy is None:
            return build_paginated_response([], 0, page, page_size)
        filters["instance_id"] = 0

    items = await SelectionResult.filter(
        skip=skip,
        limit=limit,
        order_by=[desc(SelectionResult.signal_date), SelectionResult.rank],
        **filters,
    )
    total = await SelectionResult.count(**filters)

    # 加载证券名称
    symbols = list({r.symbol for r in items})
    sec_map: dict[str, str] = {}
    if symbols:
        secs = await Security.filter(symbol__in=symbols)
        sec_map = {s.symbol: s.name for s in secs}

    payload = []
    for r in items:
        d = r.to_dict()
        d["name"] = sec_map.get(r.symbol, "")
        # 提取因子快照便于前端展示
        if isinstance(d.get("factor_values"), dict):
            d["factor_values_flat"] = d["factor_values"].get("factor_values", {})
        payload.append(d)

    return build_paginated_response(payload, total, page, page_size)


@router.get("/results/dates", summary="查询某策略的所有信号日", operation_id="list_selection_result_dates")
async def list_signal_dates(
    strategy_id: str | None = Query(default=None, description="策略编码过滤"),
    instance_id: int | None = Query(default=None, description="策略实例ID过滤"),
) -> list[str]:
    """返回去重排序后的信号日列表，供前端做信号日下拉。"""
    filters: dict = {}
    if instance_id is not None:
        filters["instance_id"] = instance_id
    elif strategy_id is not None:
        strategy = await Strategy.get_or_none(strategy_id=strategy_id)
        if strategy is None:
            return []
        filters["instance_id"] = 0

    rows = await SelectionResult.filter(
        order_by=desc(SelectionResult.signal_date),
        limit=1000,
        **filters,
    )
    seen: set[str] = set()
    out: list[str] = []
    for r in rows:
        s = str(r.signal_date)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out
