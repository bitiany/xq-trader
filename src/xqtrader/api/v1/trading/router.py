"""交易域 API — 账户、策略实例、自选池管理"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Query, Request
from sqlalchemy import desc

from framework.commons.exceptions import BusinessException, NotFoundException
from framework.commons.logger import get_logger
from framework.commons.pagination import build_paginated_response, paginate
from framework.commons.redis_client import redis_client
from framework.commons.time_util import now_shanghai
from xqtrader.api.v1.trading.schemas import (
    AccountCreate,
    ApprovalRequest,
    BatchApprovalRequest,
    BatchPreOrderSubmitRequest,
    InstanceCreate,
    InstanceUpdate,
    KillSwitchRequest,
    ManualDecisionWorkflowRequest,
    PreOrderSubmitRequest,
    PreOrderUpdate,
    RiskEventResolveRequest,
    RiskRuleUpdate,
    WatchlistItemCreate,
    WatchlistItemUpdate,
)
from xqtrader.api.v1.workflow import execute_workflow
from xqtrader.domain.factor.models.factor_value import FacFactorValue
from xqtrader.domain.market.models.candlestick import CandlestickDaily
from xqtrader.domain.security.models import Security
from xqtrader.domain.trading.enums import (
    AccountType,
    ApprovalStatus,
    InstanceStatus,
    PreOrderStatus,
    RunMode,
)
from xqtrader.domain.trading.models.account import AccountSnapshot, TradingAccount
from xqtrader.domain.trading.models.decision import PositionSizingResult, SignalFusionResult, TradingSignal
from xqtrader.domain.trading.models.instance import StrategyInstance
from xqtrader.domain.trading.models.order import Order, PreOrder, Trade
from xqtrader.domain.trading.models.position import PositionSnapshot
from xqtrader.domain.trading.models.risk import RiskEvent, RiskRule
from xqtrader.domain.trading.models.strategy import Strategy
from xqtrader.domain.trading.models.watchlist import Watchlist, WatchlistItem
from xqtrader.domain.trading.workflow.kill_switch_service import KillSwitchService
from xqtrader.domain.watermark.models.trade_calendar import TradeCalendar
from xqtrader.ws.spi.impl.pnl import sync_account_assets_to_redis
from xqtrader.ws.spi.impl.watchlist_quotes import WATCHLIST_SYMBOLS_PREFIX

logger = get_logger(__name__)

router = APIRouter(prefix="/trading", tags=["交易"])

VALID_ACCOUNT_TYPES = {AccountType.LIVE, AccountType.PAPER}
VALID_RUN_MODES = {RunMode.LIVE_MANUAL, RunMode.LIVE_AUTO, RunMode.PAPER, RunMode.BACKTEST}
LIVE_RUN_MODES = {RunMode.LIVE_MANUAL, RunMode.LIVE_AUTO}
RISK_LEVEL_LABEL = {"info": "提示", "warn": "警告", "critical": "严重", "fatal": "致命"}
RISK_EVENT_TYPE_LABEL = {
    "blocked": "已阻断",
    "warning": "风险提示",
    "circuit_breaker": "熔断",
    "kill_switch": "紧急只减仓",
}
RISK_REASON_LABEL = {
    "blacklisted": "命中黑名单",
    "max_single_weight_exceeded": "单标的仓位超过上限",
    "max_total_weight_exceeded": "组合总仓位超过上限",
    "account_reduce_only": "账户处于仅减仓模式",
    "manual_kill_switch": "人工触发紧急只减仓",
    "no_position_to_reduce": "无可减仓持仓",
}
RISK_ACTION_LABEL = {
    "pre_order_blocked": "已阻断该标的预订单",
    "all_pre_orders_blocked": "已阻断本轮信号预订单",
    "reduce_only_and_close_pre_orders_generated": "已切换仅减仓并生成平仓预订单",
}


# ==================== 辅助函数 ====================


async def _build_security_name_map(symbols: list[str]) -> dict[str, str]:
    if not symbols:
        return {}
    securities = await Security.filter(symbol__in=list(set(symbols)), limit=None)
    return {sec.symbol: sec.name for sec in securities if sec.name}


def _build_signal_detail(
    *,
    signal: TradingSignal | None,
    fusion: SignalFusionResult | None,
    risk_check_detail: dict | None,
) -> dict | None:
    if signal is None and fusion is None and not risk_check_detail:
        return None
    raw = signal.raw_values if signal and isinstance(signal.raw_values, dict) else {}
    entry_price_detail = None
    if isinstance(risk_check_detail, dict):
        entry_price_detail = risk_check_detail.get("entry_price_detail")
    return {
        "direction": signal.direction if signal else None,
        "confidence": raw.get("confidence"),
        "strength": signal.strength if signal else None,
        "score": raw.get("score"),
        "reason": raw.get("reason"),
        "strategy_id": raw.get("strategy_id"),
        "fused_score": fusion.fused_score if fusion else None,
        "factor_values": raw.get("factor_values"),
        "market_data": raw.get("market_data"),
        "entry_price_detail": entry_price_detail,
    }


async def _load_signal_context(
    instance_ids: list[int],
    symbols: list[str],
    signal_dates: list[date],
) -> tuple[dict, dict, dict, dict]:
    if not instance_ids or not symbols or not signal_dates:
        return {}, {}, {}, {}
    signal_filters: dict = {
        "instance_id__in": instance_ids,
        "symbol__in": symbols,
        "signal_date__in": signal_dates,
    }
    signals = await TradingSignal.filter(
        **signal_filters,
        order_by=desc(TradingSignal.id),
    )
    fusion_results = await SignalFusionResult.filter(
        **signal_filters,
        order_by=desc(SignalFusionResult.id),
    )
    signal_by_run: dict[tuple, TradingSignal] = {}
    signal_by_date: dict[tuple, TradingSignal] = {}
    fusion_by_run: dict[tuple, SignalFusionResult] = {}
    fusion_by_date: dict[tuple, SignalFusionResult] = {}
    for signal_item in signals:
        date_key = (signal_item.instance_id, signal_item.symbol, signal_item.signal_date)
        run_key = (signal_item.instance_id, signal_item.workflow_run_id, signal_item.symbol, signal_item.signal_date)
        signal_by_run[run_key] = signal_item
        if date_key not in signal_by_date:
            signal_by_date[date_key] = signal_item
    for fusion_item in fusion_results:
        date_key = (fusion_item.instance_id, fusion_item.symbol, fusion_item.signal_date)
        run_key = (fusion_item.instance_id, fusion_item.workflow_run_id, fusion_item.symbol, fusion_item.signal_date)
        fusion_by_run[run_key] = fusion_item
        if date_key not in fusion_by_date:
            fusion_by_date[date_key] = fusion_item
    return signal_by_run, signal_by_date, fusion_by_run, fusion_by_date


def _resolve_signal_for_pre_order(
    pre_order: PreOrder,
    signal_by_run: dict,
    signal_by_date: dict,
    fusion_by_run: dict,
    fusion_by_date: dict,
) -> tuple[TradingSignal | None, SignalFusionResult | None]:
    run_key = (pre_order.instance_id, pre_order.workflow_run_id, pre_order.symbol, pre_order.signal_date)
    date_key = (pre_order.instance_id, pre_order.symbol, pre_order.signal_date)
    signal = signal_by_run.get(run_key) or signal_by_date.get(date_key)
    fusion = fusion_by_run.get(run_key) or fusion_by_date.get(date_key)
    return signal, fusion


async def _get_account_or_404(account_id: int) -> TradingAccount:
    account = await TradingAccount.get_or_none(id=account_id)
    if account is None:
        raise NotFoundException(message=f"账户不存在: {account_id}")
    if account.account_type not in VALID_ACCOUNT_TYPES:
        raise BusinessException(message=f"账户类型不合法: {account.account_type}")
    return account


async def _get_instance_or_404(instance_id: int) -> StrategyInstance:
    instance = await StrategyInstance.get_or_none(id=instance_id)
    if instance is None:
        raise NotFoundException(message=f"策略实例不存在: {instance_id}")
    return instance


async def _get_watchlist_item_or_404(item_id: int) -> WatchlistItem:
    item = await WatchlistItem.get_or_none(id=item_id)
    if item is None:
        raise NotFoundException(message=f"自选股不存在: {item_id}")
    return item


async def _validate_timing_strategy_id(signal_config: dict | None) -> None:
    if not signal_config:
        return
    strategy_id = signal_config.get("strategy_id")
    if not strategy_id:
        return
    strategy = await Strategy.get_or_none(strategy_id=strategy_id)
    if strategy is None:
        raise BusinessException(message=f"策略不存在: {strategy_id}")
    if strategy.strategy_type != "timing":
        raise BusinessException(message=f"自选标的只能绑定时序交易信号策略: {strategy_id}")
    if strategy.status != "active":
        raise BusinessException(message=f"策略未启用: {strategy_id}")


async def _sync_watchlist_quote_symbols(account_id: int | None = None) -> None:
    """同步自选股 symbols 到 Redis，按账户维度存储。

    Args:
        account_id: 指定账户则只同步该账户；None 则同步所有账户。
    """
    if account_id is not None:
        watchlist = await Watchlist.get_or_none(account_id=account_id)
        key = f"{WATCHLIST_SYMBOLS_PREFIX}:{account_id}:quote_symbols"
        redis_client.delete(key)
        if watchlist:
            items = await WatchlistItem.filter(watchlist_id=watchlist.id, is_enabled=1)
            symbols = sorted({item.symbol for item in items})
            if symbols:
                redis_client.sadd(key, *symbols)
        return

    # 同步所有账户
    all_watchlists = await Watchlist.all()
    for wl in all_watchlists:
        items = await WatchlistItem.filter(watchlist_id=wl.id, is_enabled=1)
        key = f"{WATCHLIST_SYMBOLS_PREFIX}:{wl.account_id}:quote_symbols"
        redis_client.delete(key)
        symbols = sorted({item.symbol for item in items})
        if symbols:
            redis_client.sadd(key, *symbols)


def _decision_run_mode_for_account(account: TradingAccount) -> str:
    if account.account_type == AccountType.PAPER:
        return RunMode.PAPER
    return RunMode.LIVE_MANUAL


def _instance_run_mode_matches_account(account: TradingAccount, run_mode: str) -> bool:
    if account.account_type == AccountType.PAPER:
        return run_mode == RunMode.PAPER
    return run_mode in LIVE_RUN_MODES


async def _build_watchlist_strategy_bindings(account_id: int) -> list[dict]:
    watchlist = await Watchlist.get_or_none(account_id=account_id)
    if watchlist is None:
        return []
    items = await WatchlistItem.filter(watchlist_id=watchlist.id, is_enabled=1, limit=None)
    strategy_ids = sorted({
        str(item.signal_config["strategy_id"])
        for item in items
        if isinstance(item.signal_config, dict) and item.signal_config.get("strategy_id")
    })
    strategies = await Strategy.filter(strategy_id__in=strategy_ids, limit=None) if strategy_ids else []
    strategy_map = {strategy.strategy_id: strategy for strategy in strategies}
    return [
        {
            "strategy_id": strategy_id,
            "name": strategy_map[strategy_id].name if strategy_id in strategy_map else strategy_id,
            "symbols": sorted({
                item.symbol
                for item in items
                if isinstance(item.signal_config, dict)
                and item.signal_config.get("strategy_id") == strategy_id
            }),
        }
        for strategy_id in strategy_ids
    ]


async def _create_account_decision_instance(
    account_id: int,
    watchlist_strategies: list[dict] | None = None,
) -> StrategyInstance:
    account = await _get_account_or_404(account_id)
    now = now_shanghai()
    return await StrategyInstance.create(
        account_id=account_id,
        strategy_id=None,
        instance_name="自选标的盘后信号工作流",
        run_mode=_decision_run_mode_for_account(account),
        status=InstanceStatus.RUNNING,
        config={"pool_id": "all", "watchlist_strategies": watchlist_strategies or []},
        position_sizing={"mode": "watchlist_target_weight", "max_total_weight": 1.0},
        risk_overrides={"blacklist": [], "max_total_weight": 1.0, "max_single_weight": 0.2},
        universe_pool="watchlist",
        started_at=now,
        description="账户自选标的盘后信号工作流实例",
    )


async def _sync_account_decision_instances(account_id: int | None) -> None:
    if account_id is None:
        return
    account = await _get_account_or_404(account_id)
    bindings = await _build_watchlist_strategy_bindings(account_id)
    instances = await StrategyInstance.filter(
        account_id=account_id,
        universe_pool="watchlist",
        limit=None,
    )
    valid_instances = [
        instance
        for instance in instances
        if _instance_run_mode_matches_account(account, instance.run_mode)
    ]
    if not valid_instances and bindings:
        await _create_account_decision_instance(account_id, bindings)
        return
    for instance in valid_instances:
        config = dict(instance.config or {})
        config["watchlist_strategies"] = bindings
        await instance.update({"config": config})


# ==================== 账户 API ====================


@router.get("/accounts", summary="账户列表", operation_id="list_accounts")
async def list_accounts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500),
    account_type: str | None = Query(default=None, description="账户类型过滤: live/paper"),
) -> dict:
    skip, limit = paginate(page, page_size)
    filters: dict = {}
    if account_type:
        filters["account_type"] = account_type

    items = await TradingAccount.filter(
        skip=skip, limit=limit,
        order_by=desc(TradingAccount.updated_at),
        **filters,
    )
    total = await TradingAccount.count(**filters)

    return build_paginated_response(
        [a.to_dict() for a in items], total, page, page_size,
    )


@router.post("/accounts", summary="创建账户", operation_id="create_account")
async def create_account(req: AccountCreate) -> dict:
    if req.account_type not in VALID_ACCOUNT_TYPES:
        raise BusinessException(message=f"账户类型不合法: {req.account_type}")
    existing = await TradingAccount.get_or_none(account_code=req.account_code)
    if existing is not None:
        raise BusinessException(message=f"账户编码已存在: {req.account_code}")
    account = await TradingAccount.create(**req.model_dump())
    await sync_account_assets_to_redis()
    return account.to_dict()


@router.get("/accounts/{account_id}", summary="账户详情", operation_id="get_account")
async def get_account(account_id: int) -> dict:
    account = await _get_account_or_404(account_id)
    return account.to_dict()


@router.post(
    "/accounts/{account_id}/kill-switch",
    summary="账户紧急全平 — 绕过审批直连 Broker",
    operation_id="enable_account_kill_switch",
)
async def enable_account_kill_switch(
    account_id: int,
    req: KillSwitchRequest,
) -> dict:
    """触发账户紧急全平：
    1. 设置 reduce_only=True 阻断新买入
    2. 写入 FATAL 级 kill_switch 风控事件
    3. 取消所有 SUBMITTED 挂单
    4. 对每个持仓生成 close 预订单（APPROVED）+ Order（CREATED）
    5. 直接提交到模拟撮合或 QMT，不经过人工审批
    """
    service = KillSwitchService.get_instance()
    result = await service.execute(
        account_id=account_id,
        operator=req.operator,
        reason=req.reason,
    )
    return result


@router.get(
    "/accounts/{account_id}/snapshot",
    summary="最新资金快照",
    operation_id="get_account_snapshot",
)
async def get_account_snapshot(account_id: int) -> dict:
    account = await _get_account_or_404(account_id)
    snapshot = await AccountSnapshot.filter(
        account_id=account_id,
        limit=1,
        order_by=desc(AccountSnapshot.snapshot_date),
    )
    available_cash = float(account.available_cash)
    frozen_cash = float(account.frozen_cash)
    if snapshot:
        data = snapshot[0].to_dict()
        market_value = float(data["market_value"])
        data["available_cash"] = available_cash
        data["frozen_cash"] = frozen_cash
        data["total_assets"] = available_cash + frozen_cash + market_value
        return data
    return {
        "account_id": account_id,
        "snapshot_date": None,
        "total_assets": available_cash + frozen_cash,
        "market_value": 0,
        "available_cash": available_cash,
        "frozen_cash": frozen_cash,
        "daily_pnl": 0,
        "cumulative_pnl": 0,
        "daily_return": 0,
        "position_count": 0,
        "snapshot_time": None,
    }


@router.get(
    "/accounts/{account_id}/snapshots",
    summary="资金快照历史",
    operation_id="list_account_snapshots",
)
async def list_account_snapshots(
    account_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=31, ge=1, le=366),
) -> dict:
    await _get_account_or_404(account_id)
    skip, limit = paginate(page, page_size)
    filters = {"account_id": account_id}
    items = await AccountSnapshot.filter(
        skip=skip,
        limit=limit,
        order_by=desc(AccountSnapshot.snapshot_date),
        **filters,
    )
    total = await AccountSnapshot.count(**filters)
    return build_paginated_response([item.to_dict() for item in items], total, page, page_size)


# ==================== 策略实例 API ====================


@router.get("/instances", summary="实例列表", operation_id="list_instances")
async def list_instances(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500),
    account_id: int | None = Query(default=None, description="账户ID过滤"),
    status: str | None = Query(default=None, description="状态过滤"),
    run_mode: str | None = Query(default=None, description="运行模式过滤"),
) -> dict:
    skip, limit = paginate(page, page_size)
    filters: dict = {}
    scoped_account: TradingAccount | None = None
    if account_id is not None:
        scoped_account = await _get_account_or_404(account_id)
        filters["account_id"] = account_id
    if status:
        filters["status"] = status
    if run_mode:
        if run_mode not in VALID_RUN_MODES:
            raise BusinessException(message=f"实例运行模式不合法: {run_mode}")
        if scoped_account is not None and not _instance_run_mode_matches_account(scoped_account, run_mode):
            raise BusinessException(message="运行模式与账户类型不匹配")
        filters["run_mode"] = run_mode

    if scoped_account is not None and run_mode is None:
        if scoped_account.account_type == AccountType.PAPER:
            filters["run_mode"] = RunMode.PAPER
        else:
            filters["run_mode__in"] = list(LIVE_RUN_MODES)
    items = await StrategyInstance.filter(
        skip=skip, limit=limit,
        order_by=desc(StrategyInstance.updated_at),
        **filters,
    )
    total = await StrategyInstance.count(**filters)
    result_items = []
    for item in items:
        data = item.to_dict()
        config = dict(data.get("config") or {})
        if item.universe_pool == "watchlist" and account_id is not None:
            config["watchlist_strategies"] = await _build_watchlist_strategy_bindings(account_id)
        data["config"] = config
        result_items.append(data)
    return build_paginated_response(
        result_items, total, page, page_size,
    )


@router.post("/instances", summary="创建实例", operation_id="create_instance")
async def create_instance(req: InstanceCreate) -> dict:
    account = await _get_account_or_404(req.account_id)
    payload = req.model_dump()
    run_mode = str(payload["run_mode"])
    if run_mode not in VALID_RUN_MODES:
        raise BusinessException(message=f"实例运行模式不合法: {run_mode}")
    if account.account_type == AccountType.PAPER and run_mode != RunMode.PAPER:
        raise BusinessException(message="模拟账户只能创建模拟盘策略实例")
    if account.account_type == AccountType.LIVE and run_mode not in LIVE_RUN_MODES:
        raise BusinessException(message="实盘账户只能创建实盘策略实例")
    instance = await StrategyInstance.create(**payload)
    return instance.to_dict()


@router.get(
    "/instances/{instance_id}", summary="实例详情", operation_id="get_instance",
)
async def get_instance(instance_id: int) -> dict:
    instance = await _get_instance_or_404(instance_id)
    return instance.to_dict()


@router.put(
    "/instances/{instance_id}", summary="更新实例配置", operation_id="update_instance",
)
async def update_instance(instance_id: int, req: InstanceUpdate) -> dict:
    instance = await _get_instance_or_404(instance_id)
    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    if payload:
        await instance.update(payload)
    return instance.to_dict()


@router.post(
    "/instances/{instance_id}/start",
    summary="启动实例",
    operation_id="start_instance",
)
async def start_instance(instance_id: int) -> dict:
    instance = await _get_instance_or_404(instance_id)
    now = now_shanghai()
    await instance.update({"status": "running", "started_at": now})
    return instance.to_dict()


@router.post(
    "/instances/{instance_id}/pause",
    summary="暂停实例",
    operation_id="pause_instance",
)
async def pause_instance(instance_id: int) -> dict:
    instance = await _get_instance_or_404(instance_id)
    await instance.update({"status": "paused"})
    return instance.to_dict()


@router.post(
    "/instances/{instance_id}/stop",
    summary="停止实例",
    operation_id="stop_instance",
)
async def stop_instance(instance_id: int) -> dict:
    instance = await _get_instance_or_404(instance_id)
    now = now_shanghai()
    await instance.update({"status": "stopped", "stopped_at": now})
    return instance.to_dict()


async def _resolve_decision_signal_date(signal_date: str | None) -> date:
    if signal_date:
        return date.fromisoformat(signal_date)
    latest_factor = await FacFactorValue.filter(limit=1, order_by=desc(FacFactorValue.trade_date))
    latest_bar = await CandlestickDaily.filter(limit=1, order_by=desc(CandlestickDaily.trade_date))
    latest_trade = await TradeCalendar.get_latest_trade_date()
    candidates: list[date] = []
    if latest_factor:
        candidates.append(latest_factor[0].trade_date)
    if latest_bar:
        candidates.append(latest_bar[0].trade_date)
    if latest_trade is not None:
        candidates.append(latest_trade)
    if not candidates:
        raise BusinessException(message="没有可用于运行信号工作流的因子/行情数据")
    resolved = min(candidates)
    logger.info(
        "决策流解析信号日 | factor=%s bar=%s calendar=%s resolved=%s",
        latest_factor[0].trade_date if latest_factor else None,
        latest_bar[0].trade_date if latest_bar else None,
        latest_trade,
        resolved,
    )
    return resolved


async def _resolve_decision_execution_date(signal_date: date, execution_date: str | None) -> date:
    if execution_date:
        return date.fromisoformat(execution_date)
    next_trade = await TradeCalendar.get_next_trade_date(signal_date)
    if next_trade is None:
        raise BusinessException(message=f"无法解析执行日：信号日 {signal_date} 之后无交易日")
    return next_trade


async def _get_account_decision_instance(account_id: int) -> StrategyInstance:
    account = await _get_account_or_404(account_id)
    instances = await StrategyInstance.filter(
        account_id=account_id,
        status=InstanceStatus.RUNNING,
        universe_pool="watchlist",
        limit=None,
        order_by=desc(StrategyInstance.updated_at),
    )
    valid_instances = [
        instance
        for instance in instances
        if _instance_run_mode_matches_account(account, instance.run_mode)
    ]
    if valid_instances:
        return valid_instances[0]

    watchlist = await Watchlist.get_or_none(account_id=account_id)
    if watchlist is None:
        raise BusinessException(message=f"账户没有自选池，无法手动运行信号工作流: {account_id}")
    configured_count = await WatchlistItem.count(watchlist_id=watchlist.id, is_enabled=1)
    if configured_count <= 0:
        raise BusinessException(message=f"账户自选池为空，无法手动运行信号工作流: {account_id}")

    watchlist_strategies = await _build_watchlist_strategy_bindings(account_id)
    return await _create_account_decision_instance(account_id, watchlist_strategies)


async def _try_get_active_decision_instance_id(account_id: int) -> int | None:
    """返回账户当前运行中的决策实例 ID；不存在时不自动创建。"""
    account = await TradingAccount.get_or_none(id=account_id)
    if account is None:
        return None
    instances = await StrategyInstance.filter(
        account_id=account_id,
        status=InstanceStatus.RUNNING,
        universe_pool="watchlist",
        limit=None,
        order_by=desc(StrategyInstance.updated_at),
    )
    valid_instances = [
        instance
        for instance in instances
        if _instance_run_mode_matches_account(account, instance.run_mode)
    ]
    if valid_instances:
        return valid_instances[0].id
    return None


async def _get_active_decision_instance_id(account_id: int) -> int:
    instance_id = await _try_get_active_decision_instance_id(account_id)
    if instance_id is not None:
        return instance_id
    return (await _get_account_decision_instance(account_id)).id


@router.get(
    "/accounts/{account_id}/decision-workflow/instance",
    summary="账户当前盘后信号工作流实例",
    operation_id="get_account_decision_workflow_instance",
)
async def get_account_decision_workflow_instance(account_id: int) -> dict:
    instance = await _get_account_decision_instance(account_id)
    data = instance.to_dict()
    config = dict(data.get("config") or {})
    config["watchlist_strategies"] = await _build_watchlist_strategy_bindings(account_id)
    data["config"] = config
    return data


@router.post(
    "/accounts/{account_id}/decision-workflow/run",
    summary="手动运行账户盘后信号工作流",
    operation_id="run_account_decision_workflow",
)
async def run_account_decision_workflow(account_id: int, req: ManualDecisionWorkflowRequest) -> dict:
    await _get_account_or_404(account_id)
    instance = await _get_account_decision_instance(account_id)
    signal_date = await _resolve_decision_signal_date(req.signal_date)
    execution_date = await _resolve_decision_execution_date(signal_date, req.execution_date)
    workflow_result = await execute_workflow(
        flow_id="watchlist_after_close_decision_flow",
        workspace_id=f"trading_account:{account_id}",
        inputs={
            "instance_id": instance.id,
            "signal_date": signal_date.isoformat(),
            "execution_date": execution_date.isoformat(),
            "lookback_days": req.lookback_days,
            "min_confidence": req.min_confidence,
            "max_selected": req.max_selected,
        },
    )
    run_id = str(workflow_result["run_id"])
    signals_count = await TradingSignal.count(instance_id=instance.id, workflow_run_id=run_id)
    fusion_count = await SignalFusionResult.count(instance_id=instance.id, workflow_run_id=run_id)
    sizing_count = await PositionSizingResult.count(instance_id=instance.id, workflow_run_id=run_id)
    pre_orders = await PreOrder.filter(
        instance_id=instance.id,
        workflow_run_id=run_id,
        approval_status=ApprovalStatus.PENDING,
        limit=None,
        order_by=desc(PreOrder.created_at),
    )
    return {
        "run": workflow_result,
        "account_id": account_id,
        "instance_id": instance.id,
        "signal_date": signal_date.isoformat(),
        "execution_date": execution_date.isoformat(),
        "signals_count": signals_count,
        "fusion_count": fusion_count,
        "sizing_count": sizing_count,
        "pre_orders_count": len(pre_orders),
        "pre_orders": [item.to_dict() for item in pre_orders],
    }


# ==================== 自选池 API ====================


@router.get(
    "/watchlists/{account_id}",
    summary="获取账户的自选池",
    operation_id="get_watchlist",
)
async def get_watchlist(account_id: int) -> dict:
    await _get_account_or_404(account_id)
    watchlist = await Watchlist.get_or_none(account_id=account_id)
    if watchlist is None:
        return {"watchlist": None, "items": []}
    items = await WatchlistItem.filter(watchlist_id=watchlist.id)
    await _sync_watchlist_quote_symbols(account_id)

    # 批量关联行情 + 名称
    symbols = [it.symbol for it in items]
    quote_map: dict[str, dict] = {}
    name_map: dict[str, str] = {}
    strategy_ids = [
        it.signal_config.get("strategy_id")
        for it in items
        if isinstance(it.signal_config, dict) and it.signal_config.get("strategy_id")
    ]
    strategies = await Strategy.filter(strategy_id__in=list(set(strategy_ids))) if strategy_ids else []
    strategy_map = {s.strategy_id: s.to_dict() for s in strategies}
    if symbols:
        # 最新行情
        for sym in symbols:
            rows: list[CandlestickDaily] = await CandlestickDaily.filter(
                symbol=sym, limit=1,
                order_by=desc(CandlestickDaily.trade_date),
            )
            if rows:
                row = rows[0]
                quote_map[sym] = {
                    "last_price": row.close,
                    "change_pct": row.pct_chg,
                    "trade_date": str(row.trade_date),
                }
        # 证券名称
        for sym in symbols:
            sec: Security | None = await Security.get_or_none(symbol=sym)
            if sec:
                name_map[sym] = sec.name

    result_items = []
    for it in items:
        d = it.to_dict()
        d["name"] = name_map.get(it.symbol, it.symbol)
        q = quote_map.get(it.symbol)
        d["last_price"] = q["last_price"] if q else None
        d["change_pct"] = q["change_pct"] if q else None
        signal_config = it.signal_config if isinstance(it.signal_config, dict) else {}
        strategy_id = signal_config.get("strategy_id")
        d["signal_strategy"] = strategy_map.get(strategy_id) if isinstance(strategy_id, str) else None
        result_items.append(d)

    return {"watchlist": watchlist.to_dict(), "items": result_items}


@router.post(
    "/watchlists/{account_id}/items",
    summary="添加自选股",
    operation_id="add_watchlist_item",
)
async def add_watchlist_item(account_id: int, req: WatchlistItemCreate) -> dict:
    await _get_account_or_404(account_id)
    await _validate_timing_strategy_id(req.signal_config)
    watchlist = await Watchlist.get_or_none(account_id=account_id)
    if watchlist is None:
        watchlist = await Watchlist.create(account_id=account_id)
    existing = await WatchlistItem.get_or_none(
        watchlist_id=watchlist.id, symbol=req.symbol,
    )
    if existing is not None:
        raise BusinessException(message=f"自选股已存在: {req.symbol}")
    item = await WatchlistItem.create(
        watchlist_id=watchlist.id, **req.model_dump(),
    )
    await _sync_watchlist_quote_symbols(account_id)
    await _sync_account_decision_instances(account_id)
    return item.to_dict()


@router.delete(
    "/watchlists/items/{item_id}",
    summary="删除自选股",
    operation_id="delete_watchlist_item",
)
async def delete_watchlist_item(item_id: int) -> dict:
    item = await _get_watchlist_item_or_404(item_id)
    watchlist = await Watchlist.get_or_none(id=item.watchlist_id)
    account_id = watchlist.account_id if watchlist else None
    await item.delete()
    await _sync_watchlist_quote_symbols(account_id)
    await _sync_account_decision_instances(account_id)
    return {"deleted": True}


@router.put(
    "/watchlists/items/{item_id}",
    summary="更新自选股配置",
    operation_id="update_watchlist_item",
)
async def update_watchlist_item(item_id: int, req: WatchlistItemUpdate) -> dict:
    item = await _get_watchlist_item_or_404(item_id)
    watchlist = await Watchlist.get_or_none(id=item.watchlist_id)
    account_id = watchlist.account_id if watchlist else None
    payload = req.model_dump(exclude_unset=True)
    if payload.get("symbol") is None:
        payload.pop("symbol", None)
    if "signal_config" in payload:
        await _validate_timing_strategy_id(payload["signal_config"])
    if "symbol" in payload and payload["symbol"] != item.symbol:
        existing = await WatchlistItem.get_or_none(
            watchlist_id=item.watchlist_id,
            symbol=payload["symbol"],
        )
        if existing is not None:
            raise BusinessException(message=f"自选股已存在: {payload['symbol']}")
    if payload:
        await item.update(payload)
        await _sync_watchlist_quote_symbols(account_id)
        await _sync_account_decision_instances(account_id)
    return item.to_dict()


# ==================== 风控规则 API ====================


@router.get(
    "/risk-rules",
    summary="风控规则列表",
    operation_id="list_risk_rules",
)
async def list_risk_rules(
    category: str | None = Query(default=None, description="类别过滤"),
    level: str | None = Query(default=None, description="级别过滤"),
) -> dict:
    filters: dict = {}
    if category:
        filters["category"] = category
    if level:
        filters["level"] = level
    items = await RiskRule.filter(**filters)
    return {"items": [r.to_dict() for r in items]}


@router.put(
    "/risk-rules/{rule_id}",
    summary="更新风控规则",
    operation_id="update_risk_rule",
)
async def update_risk_rule(rule_id: int, req: RiskRuleUpdate) -> dict:
    rule = await RiskRule.get_or_none(id=rule_id)
    if rule is None:
        raise NotFoundException(message=f"风控规则不存在: {rule_id}")
    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    if payload:
        await rule.update(payload)
    return rule.to_dict()


def _serialize_risk_event(event: RiskEvent) -> dict:
    data = event.to_dict()
    detail_value = data.get("detail")
    detail: dict = detail_value if isinstance(detail_value, dict) else {}
    raw_reasons = detail.get("reasons")
    if not isinstance(raw_reasons, list):
        raw_reasons = [detail.get("reason") or data.get("event_type")]
    reason_labels = [RISK_REASON_LABEL.get(str(reason), str(reason)) for reason in raw_reasons]
    symbol = detail.get("symbol") if isinstance(detail.get("symbol"), str) else "账户级"
    action = data.get("action_taken")
    data["display"] = {
        "level_label": RISK_LEVEL_LABEL.get(str(data.get("level")), str(data.get("level"))),
        "event_type_label": RISK_EVENT_TYPE_LABEL.get(str(data.get("event_type")), str(data.get("event_type"))),
        "reason_labels": reason_labels,
        "action_label": RISK_ACTION_LABEL.get(str(action), str(action)) if action else None,
        "summary": f"{symbol}：{'、'.join(reason_labels)}",
        "scope": "标的级" if symbol != "账户级" else "账户级",
        "reasons_text": "、".join(reason_labels),
        "relation_hint": (
            "这是账户未处理风控事件，可能来自历史阻断或账户级控制；"
            "待审批信号本身以 risk_check_passed 为准。"
        ),
    }
    return data


@router.get(
    "/risk-events",
    summary="风控事件列表",
    operation_id="list_risk_events",
)
async def list_risk_events(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    account_id: int | None = Query(default=None, description="账户ID过滤"),
    instance_id: int | None = Query(default=None, description="策略实例ID过滤"),
    resolved: bool | None = Query(default=None, description="是否已处理"),
    level: str | None = Query(default=None, description="级别过滤"),
    event_type: str | None = Query(default=None, description="事件类型过滤"),
) -> dict:
    skip, limit = paginate(page, page_size)
    filters: dict = {}
    if account_id is not None:
        await _get_account_or_404(account_id)
        filters["account_id"] = account_id
    if instance_id is not None:
        filters["instance_id"] = instance_id
    elif account_id is not None and resolved is False:
        active_instance_id = await _try_get_active_decision_instance_id(account_id)
        if active_instance_id is None:
            return build_paginated_response([], 0, page, page_size)
        filters["instance_id"] = active_instance_id
    if resolved is not None:
        filters["resolved"] = resolved
    if level:
        filters["level"] = level
    if event_type:
        filters["event_type"] = event_type

    items = await RiskEvent.filter(
        skip=skip,
        limit=limit,
        order_by=desc(RiskEvent.created_at),
        **filters,
    )
    total = await RiskEvent.count(**filters)
    return build_paginated_response(
        [_serialize_risk_event(event) for event in items], total, page, page_size,
    )


@router.put(
    "/risk-events/{event_id}/resolve",
    summary="处理风控事件",
    operation_id="resolve_risk_event",
)
async def resolve_risk_event(event_id: int, req: RiskEventResolveRequest) -> dict:
    event = await RiskEvent.get(event_id)
    if event is None:
        raise NotFoundException(message=f"风控事件不存在: {event_id}")
    if not event.resolved:
        await event.update({
            "resolved": True,
            "resolved_by": req.resolved_by,
            "resolved_at": now_shanghai(),
        })
    return _serialize_risk_event(event)


# ==================== 持仓 & 订单 API ====================


@router.get(
    "/positions",
    summary="持仓快照列表",
    operation_id="list_positions",
)
async def list_positions(
    account_id: int = Query(description="账户ID"),
    snapshot_date: date | None = Query(default=None, description="快照日期 YYYY-MM-DD"),
) -> dict:
    await _get_account_or_404(account_id)
    target_date = snapshot_date
    if target_date is None:
        latest = await PositionSnapshot.filter(
            account_id=account_id,
            limit=1,
            order_by=desc(PositionSnapshot.snapshot_date),
        )
        if not latest:
            return {"items": []}
        target_date = latest[0].snapshot_date

    items = await PositionSnapshot.filter(
        account_id=account_id,
        snapshot_date=target_date,
        limit=None,
        order_by=desc(PositionSnapshot.market_value),
    )
    items = [item for item in items if int(item.qty or 0) > 0]
    name_map = await _build_security_name_map([item.symbol for item in items])
    result_items = []
    for item in items:
        data = item.to_dict()
        data["name"] = name_map.get(item.symbol, item.symbol)
        result_items.append(data)
    return {"items": result_items}


@router.get(
    "/orders",
    summary="订单列表",
    operation_id="list_orders",
)
async def list_orders(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    account_id: int = Query(description="账户ID"),
    status: str | None = Query(default=None, description="状态过滤"),
) -> dict:
    await _get_account_or_404(account_id)
    skip, limit = paginate(page, page_size)
    filters: dict = {"account_id": account_id}
    if status:
        filters["status"] = status
    items = await Order.filter(
        skip=skip,
        limit=limit,
        order_by=[desc(Order.execution_date), desc(Order.created_at)],
        **filters,
    )
    total = await Order.count(**filters)

    pre_order_ids = [item.pre_order_id for item in items if item.pre_order_id is not None]
    pre_orders = await PreOrder.filter(id__in=pre_order_ids, limit=None) if pre_order_ids else []
    pre_order_map = {po.id: po for po in pre_orders}

    order_ids = [item.id for item in items]
    trades = await Trade.filter(order_id__in=order_ids, limit=None) if order_ids else []
    trade_time_map: dict[int, datetime] = {}
    for trade in trades:
        if trade.trade_time is None:
            continue
        existing = trade_time_map.get(trade.order_id)
        if existing is None or trade.trade_time > existing:
            trade_time_map[trade.order_id] = trade.trade_time

    instance_ids = list({item.instance_id for item in items if item.instance_id is not None})
    symbols = list({item.symbol for item in items})
    signal_dates = list({
        po.signal_date for po in pre_orders if po.signal_date is not None
    })
    signal_by_run, signal_by_date, fusion_by_run, fusion_by_date = await _load_signal_context(
        instance_ids, symbols, signal_dates,
    )
    name_map = await _build_security_name_map(symbols)

    result_items = []
    for order in items:
        data = order.to_dict()
        data["name"] = name_map.get(order.symbol, order.symbol)
        trade_time = trade_time_map.get(order.id)
        data["trade_time"] = trade_time.isoformat() if trade_time is not None else None
        pre_order = pre_order_map.get(order.pre_order_id) if order.pre_order_id is not None else None
        if pre_order is not None:
            signal, fusion = _resolve_signal_for_pre_order(
                pre_order, signal_by_run, signal_by_date, fusion_by_run, fusion_by_date,
            )
            risk_detail = pre_order.risk_check_detail if isinstance(pre_order.risk_check_detail, dict) else None
            data["signal_detail"] = _build_signal_detail(
                signal=signal,
                fusion=fusion,
                risk_check_detail=risk_detail,
            )
        else:
            data["signal_detail"] = None
        result_items.append(data)

    return build_paginated_response(result_items, total, page, page_size)


async def _run_pre_order_execution_workflow(pre_order_id: int, operator: str) -> dict:
    pre_order = await PreOrder.get(pre_order_id)
    if pre_order is None:
        raise NotFoundException(message=f"预订单不存在: {pre_order_id}")
    # 业务规则校验（账户启用/类型/审批/风控/限价等）由 execute_workflow →
    # load_execution_context → PreOrderExecutionWorkflowService._validate_pre_order
    # 内部统一执行，此处不再跨模块调用私有方法。
    workflow_result = await execute_workflow(
        flow_id="pre_order_execution_flow",
        workspace_id=f"pre_order:{pre_order_id}",
        inputs={"pre_order_id": pre_order_id, "operator": operator},
    )
    outputs = workflow_result.get("outputs") or {}
    submit_result = outputs.get("submit_qmt_order") or outputs.get("submit_simulated_order") or {}
    create_result = outputs.get("create_order") or {}
    order = submit_result.get("order") or create_result.get("order")
    if not isinstance(order, dict):
        raise BusinessException(message=f"预订单执行流未返回订单: {pre_order_id}")
    return {
        "run": workflow_result,
        "order": order,
        "submitter": submit_result.get("submitter"),
        "broker_order_id": submit_result.get("broker_order_id") or order.get("broker_order_id"),
    }


@router.post(
    "/pre-orders/{pre_order_id}/submit",
    summary="预订单下单",
    operation_id="submit_pre_order",
)
async def submit_pre_order(pre_order_id: int, req: PreOrderSubmitRequest) -> dict:
    return await _run_pre_order_execution_workflow(pre_order_id, req.operator)


@router.post(
    "/pre-orders/submit/batch",
    summary="批量预订单下单",
    operation_id="batch_submit_pre_orders",
)
async def batch_submit_pre_orders(req: BatchPreOrderSubmitRequest) -> dict:
    submitted: list[dict] = []
    failed: list[dict] = []
    for pre_order_id in req.pre_order_ids:
        try:
            submitted.append(await _run_pre_order_execution_workflow(pre_order_id, req.operator))
        except BusinessException as exc:
            failed.append({"pre_order_id": pre_order_id, "message": exc.message})
        except Exception as exc:
            logger.error("预订单批量下单失败: %s", pre_order_id, exc_info=True)
            failed.append({"pre_order_id": pre_order_id, "message": str(exc)})
    return {
        "submitted": len(submitted),
        "failed": len(failed),
        "items": submitted,
        "failures": failed,
    }


# ==================== 预订单 API ====================


@router.get(
    "/pre-orders",
    summary="预订单列表",
    operation_id="list_pre_orders",
)
async def list_pre_orders(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500),
    account_id: int | None = Query(default=None, description="账户ID"),
    instance_id: int | None = Query(default=None, description="策略实例ID"),
    status: str | None = Query(default=None, description="状态过滤"),
    approval_status: str | None = Query(default=None, description="审批状态过滤"),
    signal_date: str | None = Query(default=None, description="信号日过滤 YYYY-MM-DD"),
) -> dict:
    skip, limit = paginate(page, page_size)
    filters: dict = {}
    if account_id is not None:
        account = await _get_account_or_404(account_id)
        instances = await StrategyInstance.filter(account_id=account_id, limit=None)
        compatible_instance_ids = [
            instance.id
            for instance in instances
            if _instance_run_mode_matches_account(account, instance.run_mode)
        ]
        if not compatible_instance_ids:
            return build_paginated_response([], 0, page, page_size)
        filters["instance_id__in"] = compatible_instance_ids
    if instance_id is not None:
        filters["instance_id"] = instance_id
    if status:
        filters["status"] = status
    if approval_status:
        filters["approval_status"] = approval_status
    if signal_date:
        filters["signal_date"] = signal_date

    items = await PreOrder.filter(
        skip=skip, limit=limit,
        order_by=desc(PreOrder.created_at),
        **filters,
    )
    total = await PreOrder.count(**filters)

    # 批量查询关联信号数据，附加 signal_detail
    instance_ids = list({po.instance_id for po in items}) if items else []
    symbols = list({po.symbol for po in items}) if items else []
    signal_dates = list({po.signal_date for po in items if po.signal_date is not None}) if items else []
    signal_by_run, signal_by_date, fusion_by_run, fusion_by_date = await _load_signal_context(
        instance_ids, symbols, signal_dates,
    )
    name_map = await _build_security_name_map(symbols)

    result_items = []
    for po in items:
        d = po.to_dict()
        d["name"] = name_map.get(po.symbol, po.symbol)
        signal, fusion = _resolve_signal_for_pre_order(
            po, signal_by_run, signal_by_date, fusion_by_run, fusion_by_date,
        )
        risk_detail = d.get("risk_check_detail") if isinstance(d.get("risk_check_detail"), dict) else None
        d["signal_detail"] = _build_signal_detail(
            signal=signal,
            fusion=fusion,
            risk_check_detail=risk_detail,
        )
        result_items.append(d)

    return build_paginated_response(
        result_items, total, page, page_size,
    )


@router.get(
    "/pre-orders/{pre_order_id}",
    summary="预订单详情",
    operation_id="get_pre_order",
)
async def get_pre_order(pre_order_id: int) -> dict:
    po = await PreOrder.get_or_none(id=pre_order_id)
    if po is None:
        raise NotFoundException(message=f"预订单不存在: {pre_order_id}")
    return po.to_dict()


@router.put(
    "/pre-orders/{pre_order_id}",
    summary="修改预订单",
    operation_id="update_pre_order",
)
async def update_pre_order(pre_order_id: int, req: PreOrderUpdate) -> dict:
    po = await PreOrder.get_or_none(id=pre_order_id)
    if po is None:
        raise NotFoundException(message=f"预订单不存在: {pre_order_id}")
    if po.approval_status != ApprovalStatus.PENDING:
        raise BusinessException(message="仅待审批状态可修改")
    payload = req.model_dump(exclude_unset=True)
    approval_execution = payload.pop("approval_execution", None)
    if approval_execution is not None:
        risk_detail = po.risk_check_detail if isinstance(po.risk_check_detail, dict) else {}
        payload["risk_check_detail"] = risk_detail | {"approval_execution": approval_execution}
    if payload:
        await po.update(payload)
    return po.to_dict()


def _resolve_audit_comment(comment: str, request: Request) -> str:
    """将客户端 IP/UA 附加到审批意见，作为审计依据。"""
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    audit = f"[ip={client_ip};ua={user_agent[:120]}]"
    return f"{comment} {audit}".strip() if comment else audit


# ==================== 审批 API ====================


@router.post(
    "/approval/batch",
    summary="批量审批",
    operation_id="batch_approve_pre_orders",
)
async def batch_approve_pre_orders(req: BatchApprovalRequest, request: Request) -> dict:
    now = now_shanghai()
    audit_comment = _resolve_audit_comment(req.comment, request)
    approved_count = 0
    rejected_count = 0
    skipped_count = 0
    for po_id in req.pre_order_ids:
        po = await PreOrder.get_or_none(id=po_id)
        if po is None or po.approval_status != ApprovalStatus.PENDING:
            skipped_count += 1
            continue
        if req.approved:
            await po.update({
                "approval_status": ApprovalStatus.APPROVED,
                "status": PreOrderStatus.APPROVED,
                "approved_by": req.approved_by,
                "approved_at": now,
                "approval_comment": audit_comment,
            })
            approved_count += 1
        else:
            await po.update({
                "approval_status": ApprovalStatus.REJECTED,
                "status": PreOrderStatus.REJECTED,
                "approved_by": req.approved_by,
                "approved_at": now,
                "approval_comment": audit_comment,
            })
            rejected_count += 1
    return {
        "approved": approved_count,
        "rejected": rejected_count,
        "skipped": skipped_count,
    }


@router.post(
    "/approval/{pre_order_id}",
    summary="逐条审批",
    operation_id="approve_pre_order",
)
async def approve_pre_order(pre_order_id: int, req: ApprovalRequest, request: Request) -> dict:
    po = await PreOrder.get_or_none(id=pre_order_id)
    if po is None:
        raise NotFoundException(message=f"预订单不存在: {pre_order_id}")
    if po.approval_status != ApprovalStatus.PENDING:
        raise BusinessException(message=f"当前审批状态为 {po.approval_status}，不可重复审批")
    now = now_shanghai()
    audit_comment = _resolve_audit_comment(req.comment, request)
    if req.approved:
        await po.update({
            "approval_status": ApprovalStatus.APPROVED,
            "status": PreOrderStatus.APPROVED,
            "approved_by": req.approved_by,
            "approved_at": now,
            "approval_comment": audit_comment,
        })
    else:
        await po.update({
            "approval_status": ApprovalStatus.REJECTED,
            "status": PreOrderStatus.REJECTED,
            "approved_by": req.approved_by,
            "approved_at": now,
            "approval_comment": audit_comment,
        })
    return po.to_dict()
