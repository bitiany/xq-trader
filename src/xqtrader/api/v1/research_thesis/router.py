"""投研论点卡 API — 个股基本面慢变量（五步法产物）

业务域：投研结论沉淀，与智能体会话/语义记忆无关。
会话历史、语义经验召回由 Agent Harness 自动管理，不通过 MCP 暴露。
"""

from datetime import date
from typing import Any, cast

from fastapi import APIRouter, Body
from pydantic import BaseModel

from xqtrader.domain.agent.services.thesis_service import ThesisService

router = APIRouter(prefix="/research-thesis", tags=["投研论点卡"])

_thesis_service = ThesisService()


class ThesisSaveRequest(BaseModel):
    symbol: str
    as_of: date
    valid_until: date
    direction: str
    info_gap: dict[str, Any]
    logic_gap: dict[str, Any]
    surprise_gap: dict[str, Any]
    catalysts: dict[str, Any]
    core_assumption: str
    falsification: dict[str, Any]
    tracking_metrics: dict[str, Any]
    invalidation_rules: dict[str, Any]


class ThesisStaleRequest(BaseModel):
    reason: str = ""


@router.get("/{symbol}", summary="读取投研论点卡", operation_id="get_stock_thesis")
async def get_stock_thesis(symbol: str) -> dict:
    """读取指定标的的最新有效论点卡（慢变量基本面结论）"""
    result = await _thesis_service.get_thesis(symbol)
    return result if result else {}


@router.post("", summary="保存投研论点卡", operation_id="save_stock_thesis")
async def save_stock_thesis(req: ThesisSaveRequest) -> dict:
    """保存论点卡（旧 active 标记 stale，新记录写入）"""
    return cast(dict, await _thesis_service.save_thesis(
        symbol=req.symbol,
        as_of=req.as_of,
        valid_until=req.valid_until,
        direction=req.direction,
        info_gap=req.info_gap,
        logic_gap=req.logic_gap,
        surprise_gap=req.surprise_gap,
        catalysts=req.catalysts,
        core_assumption=req.core_assumption,
        falsification=req.falsification,
        tracking_metrics=req.tracking_metrics,
        invalidation_rules=req.invalidation_rules,
    ))


@router.post(
    "/{symbol}/stale",
    summary="标记论点卡失效",
    operation_id="mark_thesis_stale",
)
async def mark_thesis_stale(
    symbol: str,
    req: ThesisStaleRequest = Body(default=ThesisStaleRequest()),
) -> dict:
    """标记指定标的的论点卡为 stale（触发五步法重算）"""
    count = await _thesis_service.mark_stale(symbol, req.reason)
    return {"affected": count}
