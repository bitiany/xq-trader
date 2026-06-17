"""规则注册表 API — 规则浏览 + 因子依赖。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from framework.commons.exceptions import BusinessException, ConflictException, NotFoundException
from framework.commons.pagination import build_paginated_response, paginate
from xqtrader.api.v1.rules.schemas import RuleCreate, RuleUpdate
from xqtrader.domain.trading.models.rule import RuleFactorDep
from xqtrader.domain.trading.models.rule import RuleRegistry as RuleRegistryModel

router = APIRouter(prefix="/rules", tags=["规则注册表"])


@router.get("", summary="规则列表")
async def list_rules(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    category: str | None = Query(default=None, description="cross_section/time_series/both"),
    type: str | None = Query(default=None, description="expression/spi"),
    status: str | None = Query(default=None, description="active/deprecated"),
    keyword: str | None = Query(default=None, description="按名称模糊搜索"),
) -> dict:
    skip, limit = paginate(page, page_size)
    filters: dict = {}
    if category:
        filters["category"] = category
    if type:
        filters["type"] = type
    if status:
        filters["status"] = status
    if keyword:
        filters["name__like"] = f"%{keyword}%"

    items = await RuleRegistryModel.filter(skip=skip, limit=limit, **filters)
    total = await RuleRegistryModel.count(**filters)
    return build_paginated_response(
        [r.to_dict() for r in items], total, page, page_size,
    )


@router.post("", summary="创建表达式规则")
async def create_rule(req: RuleCreate) -> dict:
    """创建用户自定义表达式规则。

    策略管理页的“新增规则绑定”会先基于因子与表达式创建规则，再绑定到规则组。
    """
    if req.type != "expression":
        raise BusinessException(message="仅支持创建用户自定义表达式规则")
    existing = await RuleRegistryModel.get_or_none(rule_id=req.rule_id)
    if existing is not None:
        raise ConflictException(message=f"规则编码已存在: {req.rule_id}")

    payload = req.model_dump()
    payload["is_builtin"] = False
    rule = await RuleRegistryModel.create(**payload)
    for factor_id in req.factors:
        await RuleFactorDep.create(
            rule_id=req.rule_id,
            factor_id=factor_id,
            usage="用户自定义表达式",
        )
    return rule.to_dict()


@router.get("/{rule_id}", summary="规则详情")
async def get_rule(rule_id: str) -> dict:
    rule = await RuleRegistryModel.get_or_none(rule_id=rule_id)
    if rule is None:
        raise NotFoundException(message=f"规则不存在: {rule_id}")
    return rule.to_dict()


@router.put("/{rule_id}", summary="更新表达式规则")
async def update_rule(rule_id: str, req: RuleUpdate) -> dict:
    rule = await RuleRegistryModel.get_or_none(rule_id=rule_id)
    if rule is None:
        raise NotFoundException(message=f"规则不存在: {rule_id}")
    if rule.type != "expression" or rule.is_builtin:
        raise BusinessException(message="仅支持编辑用户自定义表达式规则")
    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    if payload:
        await rule.update(payload)
    if req.factors is not None:
        await RuleFactorDep.delete_many(rule_id=rule_id)
        for factor_id in req.factors:
            await RuleFactorDep.create(
                rule_id=rule_id,
                factor_id=factor_id,
                usage="表达式依赖",
            )
    return rule.to_dict()


@router.get("/{rule_id}/factors", summary="规则依赖因子列表")
async def get_rule_factors(rule_id: str) -> list[dict]:
    deps = await RuleFactorDep.filter(rule_id=rule_id)
    return [d.to_dict() for d in deps]
