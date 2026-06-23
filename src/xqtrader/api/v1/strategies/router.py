"""策略管理 API — 策略 CRUD（单 config JSONB 形式）

规则组与组间融合内嵌在 Strategy.config 中，不再有独立的 rule_group / binding 表。
前端编辑器一次性读写整个 config，简化交互。
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import desc

from framework.commons.exceptions import BusinessException, NotFoundException
from framework.commons.pagination import build_paginated_response, paginate
from xqtrader.api.v1.strategies.schemas import StrategyCreate, StrategyUpdate
from xqtrader.domain.trading.models.rule import RuleRegistry as RuleRegistryModel
from xqtrader.domain.trading.models.strategy import Strategy

router = APIRouter(prefix="/strategies", tags=["策略管理"])


async def _get_strategy_or_404(strategy_id: str) -> Strategy:
    strategy = await Strategy.get_or_none(strategy_id=strategy_id)
    if strategy is None:
        raise NotFoundException(message=f"策略不存在: {strategy_id}")
    return strategy


# ==================== 策略 CRUD ====================

@router.get("", summary="策略列表", operation_id="list_strategies")
async def list_strategies(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500),
    strategy_type: str | None = Query(default=None, description="类型过滤: selection/timing"),
    status: str | None = Query(default=None, description="状态过滤"),
    keyword: str | None = Query(default=None, description="按名称模糊搜索"),
) -> dict:
    skip, limit = paginate(page, page_size)
    filters: dict = {}
    if strategy_type:
        filters["strategy_type"] = strategy_type
    if status:
        filters["status"] = status
    if keyword:
        filters["name__like"] = f"%{keyword}%"

    items = await Strategy.filter(
        skip=skip, limit=limit,
        order_by=desc(Strategy.updated_at),
        **filters,
    )
    total = await Strategy.count(**filters)
    return build_paginated_response(
        [s.to_dict() for s in items], total, page, page_size,
    )


@router.get("/{strategy_id}", summary="策略详情（含 config 中规则的元信息）", operation_id="get_strategy")
async def get_strategy(strategy_id: str) -> dict:
    strategy = await _get_strategy_or_404(strategy_id)

    # 收集 config 中引用的 rule_id，批量加载规则注册表的元信息
    rule_ids: set[str] = set()
    for group in strategy.config.get("groups", []):
        for rule in group.get("rules", []):
            if isinstance(rule, dict) and rule.get("rule_id"):
                rule_ids.add(rule["rule_id"])

    rule_map: dict[str, dict] = {}
    if rule_ids:
        rules = await RuleRegistryModel.filter(rule_id__in=list(rule_ids))
        rule_map = {r.rule_id: r.to_dict() for r in rules}

    return {**strategy.to_dict(), "rule_registry": rule_map}


@router.post("", summary="创建策略")
async def create_strategy(req: StrategyCreate) -> dict:
    existing = await Strategy.get_or_none(strategy_id=req.strategy_id)
    if existing is not None:
        raise BusinessException(message=f"策略编码已存在: {req.strategy_id}")
    s = await Strategy.create(**req.model_dump())
    return s.to_dict()


@router.put("/{strategy_id}", summary="更新策略")
async def update_strategy(strategy_id: str, req: StrategyUpdate) -> dict:
    s = await _get_strategy_or_404(strategy_id)
    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    if payload:
        await s.update(payload)
    return s.to_dict()


@router.delete("/{strategy_id}", summary="删除策略")
async def delete_strategy(strategy_id: str) -> dict:
    s = await _get_strategy_or_404(strategy_id)
    await s.delete()
    return {"strategy_id": strategy_id, "deleted": True}
