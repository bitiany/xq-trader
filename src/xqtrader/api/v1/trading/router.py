"""交易域 API — 账户、策略实例、自选池管理"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query
from sqlalchemy import desc

from framework.commons.exceptions import BusinessException, NotFoundException
from framework.commons.logger import get_logger
from framework.commons.pagination import build_paginated_response, paginate
from framework.commons.redis_client import redis_client
from xqtrader.api.v1.trading.schemas import (
    AccountCreate,
    ApprovalRequest,
    BatchApprovalRequest,
    InstanceCreate,
    InstanceUpdate,
    PreOrderUpdate,
    RiskRuleUpdate,
    WatchlistItemCreate,
    WatchlistItemUpdate,
)
from xqtrader.domain.market.models.candlestick import CandlestickDaily
from xqtrader.domain.security.models import Security
from xqtrader.domain.trading.enums import ApprovalStatus, PreOrderStatus
from xqtrader.domain.trading.models.account import AccountSnapshot, TradingAccount
from xqtrader.domain.trading.models.instance import StrategyInstance
from xqtrader.domain.trading.models.order import PreOrder
from xqtrader.domain.trading.models.risk import RiskRule
from xqtrader.domain.trading.models.watchlist import Watchlist, WatchlistItem
from xqtrader.ws.spi.impl.pnl import sync_account_assets_to_redis
from xqtrader.ws.spi.impl.watchlist_quotes import WATCHLIST_SYMBOLS_PREFIX

logger = get_logger(__name__)

router = APIRouter(prefix="/trading", tags=["交易"])


# ==================== 辅助函数 ====================


async def _get_account_or_404(account_id: int) -> TradingAccount:
    account = await TradingAccount.get_or_none(id=account_id)
    if account is None:
        raise NotFoundException(message=f"账户不存在: {account_id}")
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
    # 无快照时使用 td_account 基础数据
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
    if account_id is not None:
        filters["account_id"] = account_id
    if status:
        filters["status"] = status
    if run_mode:
        filters["run_mode"] = run_mode

    items = await StrategyInstance.filter(
        skip=skip, limit=limit,
        order_by=desc(StrategyInstance.updated_at),
        **filters,
    )
    total = await StrategyInstance.count(**filters)
    return build_paginated_response(
        [i.to_dict() for i in items], total, page, page_size,
    )


@router.post("/instances", summary="创建实例", operation_id="create_instance")
async def create_instance(req: InstanceCreate) -> dict:
    await _get_account_or_404(req.account_id)
    instance = await StrategyInstance.create(**req.model_dump())
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
    now = datetime.now(timezone.utc)
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
    now = datetime.now(timezone.utc)
    await instance.update({"status": "stopped", "stopped_at": now})
    return instance.to_dict()


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
        result_items.append(d)

    return {"watchlist": watchlist.to_dict(), "items": result_items}


@router.post(
    "/watchlists/{account_id}/items",
    summary="添加自选股",
    operation_id="add_watchlist_item",
)
async def add_watchlist_item(account_id: int, req: WatchlistItemCreate) -> dict:
    await _get_account_or_404(account_id)
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


# ==================== 预订单 API ====================


@router.get(
    "/pre-orders",
    summary="预订单列表",
    operation_id="list_pre_orders",
)
async def list_pre_orders(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=500),
    instance_id: int | None = Query(default=None, description="策略实例ID"),
    status: str | None = Query(default=None, description="状态过滤"),
    approval_status: str | None = Query(default=None, description="审批状态过滤"),
    signal_date: str | None = Query(default=None, description="信号日过滤 YYYY-MM-DD"),
) -> dict:
    skip, limit = paginate(page, page_size)
    filters: dict = {}
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
    return build_paginated_response(
        [po.to_dict() for po in items], total, page, page_size,
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
    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    if payload:
        await po.update(payload)
    return po.to_dict()


# ==================== 审批 API ====================


@router.post(
    "/approval/batch",
    summary="批量审批",
    operation_id="batch_approve_pre_orders",
)
async def batch_approve_pre_orders(req: BatchApprovalRequest) -> dict:
    now = datetime.now(timezone.utc)
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
                "approval_comment": req.comment,
            })
            approved_count += 1
        else:
            await po.update({
                "approval_status": ApprovalStatus.REJECTED,
                "status": PreOrderStatus.REJECTED,
                "approved_by": req.approved_by,
                "approved_at": now,
                "approval_comment": req.comment,
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
async def approve_pre_order(pre_order_id: int, req: ApprovalRequest) -> dict:
    po = await PreOrder.get_or_none(id=pre_order_id)
    if po is None:
        raise NotFoundException(message=f"预订单不存在: {pre_order_id}")
    if po.approval_status != ApprovalStatus.PENDING:
        raise BusinessException(message=f"当前审批状态为 {po.approval_status}，不可重复审批")
    now = datetime.now(timezone.utc)
    if req.approved:
        await po.update({
            "approval_status": ApprovalStatus.APPROVED,
            "status": PreOrderStatus.APPROVED,
            "approved_by": req.approved_by,
            "approved_at": now,
            "approval_comment": req.comment,
        })
    else:
        await po.update({
            "approval_status": ApprovalStatus.REJECTED,
            "status": PreOrderStatus.REJECTED,
            "approved_by": req.approved_by,
            "approved_at": now,
            "approval_comment": req.comment,
        })
    return po.to_dict()
