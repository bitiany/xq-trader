"""Agent 投研记忆 API — 论点卡 / 偏好

端点设计:
  GET  /thesis/{symbol}           读论点卡
  POST /thesis                     保存论点卡
  POST /thesis/{symbol}/stale      标记论点卡失效
  GET  /preference                 读全局偏好

说明:
  会话历史由 nanobot 框架自动管理（PgSessionManager 持久化到 PostgreSQL），
  语义经验召回由 Agent 侧 MemoryRecallHook 自动注入，二者均不再作为 MCP 工具暴露。
"""

from datetime import date
from typing import Any, cast

from fastapi import APIRouter, Body
from pydantic import BaseModel

from xqtrader.domain.agent.models.preference import AgentPreference
from xqtrader.domain.agent.services.thesis_service import ThesisService

router = APIRouter(prefix="/agent-memory", tags=["投研记忆"])

_thesis_service = ThesisService()


# ==================== Pydantic 请求模型 ====================

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


# ==================== 论点卡 ====================

@router.get("/thesis/{symbol}", summary="读取投研论点卡", operation_id="get_stock_thesis")
async def get_stock_thesis(symbol: str) -> dict:
    """读取指定标的的最新有效论点卡（慢变量基本面结论）"""
    result = await _thesis_service.get_thesis(symbol)
    return result if result else {}


@router.post("/thesis", summary="保存投研论点卡", operation_id="save_stock_thesis")
async def save_stock_thesis(req: ThesisSaveRequest) -> dict:
    """保存论点卡（旧 active 标记 stale，新记录写入 + Qdrant 索引）"""
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


@router.post("/thesis/{symbol}/stale", summary="标记论点卡失效", operation_id="mark_thesis_stale")
async def mark_thesis_stale(symbol: str, req: ThesisStaleRequest = Body(default=ThesisStaleRequest())) -> dict:
    """标记指定标的的论点卡为 stale（触发重算）"""
    count = await _thesis_service.mark_stale(symbol, req.reason)
    return {"affected": count}


# ==================== 偏好 ====================

@router.get("/preference", summary="读取全局偏好", operation_id="get_preference")
async def get_preference() -> dict:
    """读取全局偏好设置（单用户本地部署，id 恒为 1）"""
    pref = await AgentPreference.get_or_none(id=1)
    return pref.to_dict() if pref else {}

