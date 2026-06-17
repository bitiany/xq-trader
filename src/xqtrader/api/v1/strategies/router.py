"""策略管理 API — 策略 CRUD + 规则组 + 规则绑定。"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import desc

from framework.commons.exceptions import BusinessException, NotFoundException
from framework.commons.pagination import build_paginated_response, paginate
from xqtrader.api.v1.strategies.schemas import (
    RuleBindingCreate,
    RuleBindingUpdate,
    RuleGroupCreate,
    RuleGroupUpdate,
    StrategyCreate,
    StrategyUpdate,
)
from xqtrader.domain.trading.models.rule import RuleRegistry as RuleRegistryModel
from xqtrader.domain.trading.models.strategy import (
    Strategy,
    StrategyRuleBinding,
    StrategyRuleGroup,
)

router = APIRouter(prefix="/strategies", tags=["策略管理"])


async def _get_strategy_or_404(strategy_id: str) -> Strategy:
    strategy = await Strategy.get_or_none(strategy_id=strategy_id)
    if strategy is None:
        raise NotFoundException(message=f"策略不存在: {strategy_id}")
    return strategy


async def _get_group_for_strategy_or_404(strategy_id: str, group_id: int) -> StrategyRuleGroup:
    strategy = await _get_strategy_or_404(strategy_id)
    group = await StrategyRuleGroup.get(group_id)
    if group is None or group.strategy_id != strategy.id:
        raise NotFoundException(message=f"规则组不存在: {group_id}")
    return group


async def _get_binding_for_group_or_404(
    strategy_id: str,
    group_id: int,
    binding_id: int,
) -> StrategyRuleBinding:
    await _get_group_for_strategy_or_404(strategy_id, group_id)
    binding = await StrategyRuleBinding.get(binding_id)
    if binding is None or binding.group_id != group_id:
        raise NotFoundException(message=f"规则绑定不存在: {binding_id}")
    return binding


# ==================== 策略 CRUD ====================

@router.get("", summary="策略列表")
async def list_strategies(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500),
    status: str | None = Query(default=None, description="状态过滤"),
    keyword: str | None = Query(default=None, description="按名称模糊搜索"),
) -> dict:
    skip, limit = paginate(page, page_size)
    filters: dict = {}
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


@router.get("/{strategy_id}", summary="策略详情（含规则组与绑定）")
async def get_strategy(strategy_id: str) -> dict:
    strategy = await _get_strategy_or_404(strategy_id)

    groups = await StrategyRuleGroup.filter(strategy_id=strategy.id)
    group_payload = []
    for g in groups:
        bindings = await StrategyRuleBinding.filter(
            group_id=g.id,
            order_by=StrategyRuleBinding.sort_order,
        )
        rule_ids = [b.rule_id for b in bindings]
        rule_map: dict[str, dict] = {}
        if rule_ids:
            rules = await RuleRegistryModel.filter(rule_id__in=rule_ids)
            rule_map = {r.rule_id: r.to_dict() for r in rules}
        group_payload.append({
            **g.to_dict(),
            "bindings": [
                {**b.to_dict(), "rule": rule_map.get(b.rule_id)}
                for b in bindings
            ],
        })

    return {**strategy.to_dict(), "rule_groups": group_payload}


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


@router.delete("/{strategy_id}", summary="删除策略（级联清除规则组与绑定）")
async def delete_strategy(strategy_id: str) -> dict:
    s = await _get_strategy_or_404(strategy_id)

    groups = await StrategyRuleGroup.filter(strategy_id=s.id)
    for g in groups:
        await StrategyRuleBinding.delete_many(group_id=g.id)
    await StrategyRuleGroup.delete_many(strategy_id=s.id)
    await s.delete()
    return {"strategy_id": strategy_id, "deleted": True}


# ==================== 规则组 ====================

@router.get("/{strategy_id}/rule-groups", summary="规则组列表")
async def list_rule_groups(strategy_id: str) -> list[dict]:
    s = await _get_strategy_or_404(strategy_id)
    groups = await StrategyRuleGroup.filter(strategy_id=s.id)
    return [g.to_dict() for g in groups]


@router.post("/{strategy_id}/rule-groups", summary="新增规则组")
async def create_rule_group(strategy_id: str, req: RuleGroupCreate) -> dict:
    s = await _get_strategy_or_404(strategy_id)
    g = await StrategyRuleGroup.create(strategy_id=s.id, **req.model_dump())
    return g.to_dict()


@router.put("/{strategy_id}/rule-groups/{group_id}", summary="更新规则组")
async def update_rule_group(strategy_id: str, group_id: int, req: RuleGroupUpdate) -> dict:
    g = await _get_group_for_strategy_or_404(strategy_id, group_id)
    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    if payload:
        await g.update(payload)
    return g.to_dict()


@router.delete("/{strategy_id}/rule-groups/{group_id}", summary="删除规则组（级联清除绑定）")
async def delete_rule_group(strategy_id: str, group_id: int) -> dict:
    g = await _get_group_for_strategy_or_404(strategy_id, group_id)
    await StrategyRuleBinding.delete_many(group_id=group_id)
    await g.delete()
    return {"group_id": group_id, "deleted": True}


# ==================== 规则绑定 ====================

@router.get("/{strategy_id}/rule-groups/{group_id}/bindings", summary="规则绑定列表")
async def list_bindings(strategy_id: str, group_id: int) -> list[dict]:
    await _get_group_for_strategy_or_404(strategy_id, group_id)
    bindings = await StrategyRuleBinding.filter(
        group_id=group_id,
        order_by=StrategyRuleBinding.sort_order,
    )
    rule_ids = [b.rule_id for b in bindings]
    rule_map: dict[str, dict] = {}
    if rule_ids:
        rules = await RuleRegistryModel.filter(rule_id__in=rule_ids)
        rule_map = {r.rule_id: r.to_dict() for r in rules}

    return [
        {**b.to_dict(), "rule": rule_map.get(b.rule_id)}
        for b in bindings
    ]


@router.post("/{strategy_id}/rule-groups/{group_id}/bindings", summary="新增规则绑定")
async def create_binding(
    strategy_id: str,
    group_id: int,
    req: RuleBindingCreate,
) -> dict:
    await _get_group_for_strategy_or_404(strategy_id, group_id)
    rule = await RuleRegistryModel.get_or_none(rule_id=req.rule_id)
    if rule is None:
        raise NotFoundException(message=f"规则不存在: {req.rule_id}")
    b = await StrategyRuleBinding.create(group_id=group_id, **req.model_dump())
    return b.to_dict()


@router.put(
    "/{strategy_id}/rule-groups/{group_id}/bindings/{binding_id}",
    summary="更新规则绑定",
)
async def update_binding(
    strategy_id: str,
    group_id: int,
    binding_id: int,
    req: RuleBindingUpdate,
) -> dict:
    b = await _get_binding_for_group_or_404(strategy_id, group_id, binding_id)
    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    if payload:
        await b.update(payload)
    return b.to_dict()


@router.delete(
    "/{strategy_id}/rule-groups/{group_id}/bindings/{binding_id}",
    summary="删除规则绑定",
)
async def delete_binding(strategy_id: str, group_id: int, binding_id: int) -> dict:
    b = await _get_binding_for_group_or_404(strategy_id, group_id, binding_id)
    await b.delete()
    return {"binding_id": binding_id, "deleted": True}
