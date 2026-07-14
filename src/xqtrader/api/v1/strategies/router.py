"""策略管理 API — 策略 CRUD（单 config JSONB 形式）

规则组与组间融合内嵌在 Strategy.config 中，不再有独立的 rule_group / binding 表。
前端编辑器一次性读写整个 config，简化交互。

路由顺序约定：所有固定字面路径（signals/timing-history/strategy-stats）
必须放在动态路径 `/{strategy_id}` 之前，避免 "timing-history" 被
当作 strategy_id 捕获导致 404。
"""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Query
from sqlalchemy import desc

from framework.commons.exceptions import BusinessException, NotFoundException
from framework.commons.pagination import build_paginated_response, paginate
from xqtrader.api.v1.strategies.schemas import (
    CompareOutcomeRequest,
    StrategyCreate,
    StrategySignalRequest,
    StrategyUpdate,
    TimingHistoryRecordRequest,
)
from xqtrader.domain.trading.models.rule import RuleRegistry as RuleRegistryModel
from xqtrader.domain.trading.models.strategy import Strategy
from xqtrader.domain.trading.models.strategy_timing_history import StrategyTimingHistory
from xqtrader.domain.trading.strategy_signal import StrategySignalEvaluator
from xqtrader.domain.trading.strategy_signal.strategy_timing_service import (
    strategy_timing_service,
)

router = APIRouter(prefix="/strategies", tags=["策略管理"])

_evaluator = StrategySignalEvaluator()


async def _get_strategy_or_404(strategy_id: str) -> Strategy:
    strategy = await Strategy.get_or_none(strategy_id=strategy_id)
    if strategy is None:
        raise NotFoundException(message=f"策略不存在: {strategy_id}")
    return strategy


# ==================== 策略列表/创建（固定路径优先） ====================

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


@router.post("", summary="创建策略")
async def create_strategy(req: StrategyCreate) -> dict:
    existing = await Strategy.get_or_none(strategy_id=req.strategy_id)
    if existing is not None:
        raise BusinessException(message=f"策略编码已存在: {req.strategy_id}")
    s = await Strategy.create(**req.model_dump())
    return s.to_dict()


# ==================== 策略信号判定 ====================

@router.post(
    "/signals",
    summary="策略信号判定（批量执行 SPI 插件 evaluate）",
    operation_id="compute_strategy_signals",
)
async def compute_strategy_signals(req: StrategySignalRequest) -> dict:
    """为指定标的 + 信号日期批量执行策略信号判定。

    内部通过 strategy_name → rule_id 映射查找 SPI 插件，
    加载插件所需因子（预计算读 DB + on_demand 实时计算），
    调用 plugin.evaluate() 返回 buy/sell/neutral 信号。
    """
    if not req.strategies:
        raise BusinessException(message="strategies 不能为空")
    return await _evaluator.evaluate_signals(
        symbol=req.symbol,
        strategies=req.strategies,
        as_of=req.as_of,
    )


# ==================== 策略择时历史（§20 阶段 5） ====================

@router.post(
    "/timing-history",
    summary="记录一次 strategy-timing 信号",
    operation_id="record_strategy_timing_history",
)
async def record_strategy_timing_history(req: TimingHistoryRecordRequest) -> dict:
    """记录 strategy-timing 编排器的信号到 td_strategy_timing_history。

    用于后续走势比对与策略胜率反哺聚合权重（样本数 ≥ 30 启用）。
    """
    instance = await strategy_timing_service.record_timing(
        symbol=req.symbol,
        as_of=req.as_of,
        aggregated_signal=req.aggregated_signal,
        confidence=req.confidence,
        signals=req.signals,
        market_regime=req.market_regime,
        decision_rationale=req.decision_rationale,
    )
    # Tortoise ORM 元类动态生成 to_dict，mypy 无法静态推断返回类型，用 cast 断言
    return cast(dict, instance.to_dict())


@router.get(
    "/timing-history",
    summary="查询择时历史记录列表",
    operation_id="list_strategy_timing_history",
)
async def list_strategy_timing_history(
    symbol: str | None = Query(default=None, description="标的代码过滤"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> dict:
    skip, limit = paginate(page, page_size)
    items = await strategy_timing_service.list_history(
        symbol=symbol, skip=skip, limit=limit,
    )
    filters: dict = {}
    if symbol is not None:
        filters["symbol"] = symbol
    total = await StrategyTimingHistory.count(**filters)
    return build_paginated_response(
        [item.to_dict() for item in items], total, page, page_size,
    )


@router.post(
    "/timing-history/compare-pending",
    summary="批量比对所有未比对的择时历史",
    operation_id="compare_pending_timing_outcomes",
)
async def compare_pending_timing_outcomes(req: CompareOutcomeRequest) -> dict:
    """批量比对 as_of 已过窗口期但未回填 verdict 的择时历史记录。

    供定时任务调用（Celery beat），逐条比对并回填。
    """
    count = await strategy_timing_service.compare_pending_outcomes(
        window_days=req.window_days,
    )
    return {"compared_count": count, "window_days": req.window_days}


@router.get(
    "/timing-history/{history_id}",
    summary="查询择时历史详情",
    operation_id="get_strategy_timing_history",
)
async def get_strategy_timing_history(history_id: int) -> dict:
    record = await strategy_timing_service.get_history(history_id)
    if record is None:
        raise NotFoundException(message=f"择时历史不存在: {history_id}")
    return record.to_dict()


@router.post(
    "/timing-history/{history_id}/compare",
    summary="触发单条择时历史走势比对",
    operation_id="compare_strategy_timing_outcome",
)
async def compare_strategy_timing_outcome(
    history_id: int, req: CompareOutcomeRequest,
) -> dict:
    """按 history_id 比对后续走势并回填 actual_return/verdict。

    已比对或窗口内数据不足时返回当前记录状态。
    """
    record = await strategy_timing_service.compare_outcome(
        history_id, window_days=req.window_days,
    )
    if record is None:
        raise NotFoundException(
            message=f"走势比对失败：记录不存在或窗口内数据不足 history_id={history_id}",
        )
    return record.to_dict()


# ==================== 策略胜率统计（反哺聚合权重） ====================

@router.get(
    "/strategy-stats",
    summary="按 rule_id 查询策略胜率统计",
    operation_id="get_strategy_stats",
)
async def get_strategy_stats(
    rule_id: str = Query(..., description="SPI 插件标识，如 ts_ma_cross"),
    min_samples: int = Query(
        default=30, ge=1, le=500,
        description="启用反哺的最小样本数（默认 30）",
    ),
) -> dict:
    """按 rule_id 聚合计算策略胜率。

    样本数 >= min_samples 时 is_feedback_enabled=True，可反哺聚合权重。
    """
    return await strategy_timing_service.get_strategy_stats(
        rule_id, min_samples=min_samples,
    )


@router.get(
    "/strategy-stats/all",
    summary="查询所有策略胜率统计",
    operation_id="get_all_strategy_stats",
)
async def get_all_strategy_stats(
    min_samples: int = Query(
        default=30, ge=1, le=500,
        description="启用反哺的最小样本数（默认 30）",
    ),
) -> dict:
    """获取所有策略的胜率统计（按 win_rate 降序）。

    用于 strategy-timing 编排器在 D 阶段加载策略权重反哺表。
    """
    items = await strategy_timing_service.get_all_strategy_stats(min_samples=min_samples)
    return {"items": items, "count": len(items)}


# ==================== 策略详情/更新/删除（动态路径放最后） ====================

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
