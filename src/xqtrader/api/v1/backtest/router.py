"""回测 API 路由 — 同步执行 BacktestService + 历史结果查询"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import desc

from framework.commons.exceptions import NotFoundException
from framework.commons.pagination import build_paginated_response, paginate
from xqtrader.api.v1.backtest.schemas import BacktestRunRequest, BacktestRunResponse
from xqtrader.domain.trading.backtest.service import BacktestService
from xqtrader.domain.trading.models.backtest import BacktestResult, BacktestRun

router = APIRouter(prefix="/backtest", tags=["回测"])


@router.post("/run", summary="运行回测", operation_id="run_backtest")
async def run_backtest_api(req: BacktestRunRequest) -> BacktestRunResponse:
    """同步执行回测，返回每个标的的绩效指标。

    标的列表由调用方传入（手工指定、外部选股结果转换、自选池转换等）。
    回测引擎不感知"标的来源"，仅接收标的代码数组。
    """
    service = BacktestService()
    result = await service.execute(
        strategy_id=req.strategy_id,
        symbols=req.symbols,
        start_date=req.start_date,
        end_date=req.end_date,
        initial_cash=req.initial_cash,
        commission=req.commission,
    )
    return BacktestRunResponse(**result)


@router.get("/runs", summary="回测运行历史", operation_id="list_backtest_runs")
async def list_runs(
    strategy_id: str | None = Query(default=None, description="策略编码过滤"),
    status: str | None = Query(default=None, description="状态过滤"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> dict:
    skip, limit = paginate(page, page_size)
    filters: dict = {}
    if strategy_id:
        filters["strategy_id"] = strategy_id
    if status:
        filters["status"] = status

    items = await BacktestRun.filter(
        skip=skip, limit=limit,
        order_by=desc(BacktestRun.created_at),
        **filters,
    )
    total = await BacktestRun.count(**filters)
    return build_paginated_response(
        [r.to_dict() for r in items], total, page, page_size,
    )


@router.get("/runs/{run_id}", summary="回测运行详情", operation_id="get_backtest_run")
async def get_run(run_id: str) -> dict:
    run = await BacktestRun.get_or_none(run_id=run_id)
    if run is None:
        raise NotFoundException(message=f"回测运行不存在: {run_id}")
    result = await BacktestResult.get_or_none(run_id=run_id)
    return {
        **run.to_dict(),
        "result": result.to_dict() if result else None,
    }
