"""规则注册表 API — 规则 CRUD（单 definition JSONB 形式）

规则定义集中在 RuleRegistry.definition JSONB 中，无独立的因子依赖关系表
（factors 直接存储在 RuleRegistry.factors JSONB 字段中）。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from framework.commons.exceptions import BusinessException, ConflictException, NotFoundException
from framework.commons.pagination import build_paginated_response, paginate
from xqtrader.api.v1.rules.schemas import RuleCreate, RuleUpdate
from xqtrader.domain.trading.models.rule import RuleRegistry as RuleRegistryModel

router = APIRouter(prefix="/rules", tags=["规则注册表"])


@router.get("", summary="规则列表", operation_id="list_rules")
async def list_rules(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    category: str | None = Query(default=None, description="selection/timing/both"),
    rule_type: str | None = Query(default=None, description="expression/plugin"),
    status: str | None = Query(default=None, description="active/deprecated"),
    keyword: str | None = Query(default=None, description="按名称模糊搜索"),
) -> dict:
    skip, limit = paginate(page, page_size)
    filters: dict = {}
    if category:
        filters["category"] = category
    if rule_type:
        filters["rule_type"] = rule_type
    if status:
        filters["status"] = status
    if keyword:
        filters["name__like"] = f"%{keyword}%"

    items = await RuleRegistryModel.filter(skip=skip, limit=limit, **filters)
    total = await RuleRegistryModel.count(**filters)
    return build_paginated_response(
        [r.to_dict() for r in items], total, page, page_size,
    )


@router.post("", summary="创建规则")
async def create_rule(req: RuleCreate) -> dict:
    """创建用户自定义规则（表达式或插件类）。"""
    if req.rule_type != "expression":
        raise BusinessException(message="仅支持创建用户自定义表达式规则")
    existing = await RuleRegistryModel.get_or_none(rule_id=req.rule_id)
    if existing is not None:
        raise ConflictException(message=f"规则编码已存在: {req.rule_id}")

    payload = req.model_dump()
    payload["is_builtin"] = False
    rule = await RuleRegistryModel.create(**payload)
    return rule.to_dict()


@router.get("/{rule_id}", summary="规则详情", operation_id="get_rule")
async def get_rule(rule_id: str) -> dict:
    rule = await RuleRegistryModel.get_or_none(rule_id=rule_id)
    if rule is None:
        raise NotFoundException(message=f"规则不存在: {rule_id}")
    return rule.to_dict()


@router.put("/{rule_id}", summary="更新规则")
async def update_rule(rule_id: str, req: RuleUpdate) -> dict:
    rule = await RuleRegistryModel.get_or_none(rule_id=rule_id)
    if rule is None:
        raise NotFoundException(message=f"规则不存在: {rule_id}")
    if rule.is_builtin:
        raise BusinessException(message="内置规则不可编辑")
    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    if payload:
        await rule.update(payload)
    return rule.to_dict()


@router.delete("/{rule_id}", summary="删除规则")
async def delete_rule(rule_id: str) -> dict:
    rule = await RuleRegistryModel.get_or_none(rule_id=rule_id)
    if rule is None:
        raise NotFoundException(message=f"规则不存在: {rule_id}")
    if rule.is_builtin:
        raise BusinessException(message="内置规则不可删除")
    await rule.delete()
    return {"rule_id": rule_id, "deleted": True}
