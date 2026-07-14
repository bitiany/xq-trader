"""模拟盘 6 月全链路 T+1 回放 — 决策信号 → 审批 → T+1 模拟撮合。

用法:
    conda activate .\\.conda
    $env:ENV=".env"; $env:PYTHONPATH="src"
    python tests/trading/paper_june_replay.py
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import httpx
from fastapi import FastAPI
from sqlalchemy import asc

from framework.commons.time_util import today_shanghai
from framework.config.settings import settings
from framework.dal.datasource_loader import DatasourceLoader
from framework.dal.register import register_datasource
from xqtrader.domain.trading.models.account import AccountSnapshot, TradingAccount
from xqtrader.domain.trading.models.instance import StrategyInstance
from xqtrader.domain.trading.models.order import Order, PreOrder, Trade
from xqtrader.domain.trading.models.position import PositionSnapshot
from xqtrader.domain.watermark.models.trade_calendar import DEFAULT_TRADE_EXCHANGE, TradeCalendar

API_BASE = "http://localhost:8096/api/v1"
PAPER_ACCOUNT_ID = 1
OPERATOR = "paper-replay"
REPLAY_START = date(2026, 6, 1)
REPLAY_END = today_shanghai()
MIN_CONFIDENCE = 0.2

WATCHLIST_BINDINGS: list[tuple[str, str]] = [
    ("600188.SH", "ts_momentum_trend"),
    ("601138.SH", "ts_momentum_trend"),
    ("600580.SH", "ts_momentum_trend"),
    ("002463.SZ", "ts_momentum_trend"),
    ("600522.SH", "ts_momentum_trend"),
    ("300136.SZ", "ts_momentum_trend"),
    ("002938.SZ", "ts_momentum_trend"),
    ("600206.SH", "ts_momentum_trend"),
]


@dataclass
class ReplayStats:
    trading_days: int = 0
    decision_runs: int = 0
    signals_total: int = 0
    pre_orders_generated: int = 0
    pre_orders_approved: int = 0
    executions_attempted: int = 0
    executions_filled: int = 0
    executions_failed: int = 0
    failures: list[str] = field(default_factory=list)
    daily_log: list[dict] = field(default_factory=list)


async def _get_trading_days() -> list[date]:
    rows = await TradeCalendar.filter(
        exchange=DEFAULT_TRADE_EXCHANGE,
        is_open=True,
        cal_date__gte=REPLAY_START,
        cal_date__lte=REPLAY_END,
        limit=None,
        order_by=asc(TradeCalendar.cal_date),
    )
    if rows:
        return [row.cal_date for row in rows]
    days: list[date] = []
    current = REPLAY_START
    while current <= REPLAY_END:
        if current.weekday() < 5:
            days.append(current)
        current = date.fromordinal(current.toordinal() + 1)
    return days


async def _reset_paper_account() -> None:
    account = await TradingAccount.get(PAPER_ACCOUNT_ID)
    if account is None:
        raise RuntimeError(f"paper 账户不存在: {PAPER_ACCOUNT_ID}")
    initial = Decimal(str(account.initial_capital))
    await account.update({
        "available_cash": initial,
        "frozen_cash": Decimal("0"),
        "reduce_only": False,
    })

    instances = await StrategyInstance.filter(account_id=PAPER_ACCOUNT_ID, limit=None)
    instance_ids = [inst.id for inst in instances]

    for model, filters in [
        (PositionSnapshot, {"account_id": PAPER_ACCOUNT_ID}),
        (Order, {"account_id": PAPER_ACCOUNT_ID}),
        (Trade, {"account_id": PAPER_ACCOUNT_ID}),
        (AccountSnapshot, {"account_id": PAPER_ACCOUNT_ID}),
    ]:
        rows = await model.filter(**filters, limit=None)
        for row in rows:
            await row.delete()

    if instance_ids:
        pre_orders = await PreOrder.filter(instance_id__in=instance_ids, limit=None)
        for po in pre_orders:
            await po.delete()

    print(f"已重置 paper 账户#{PAPER_ACCOUNT_ID}：资金={initial}")


async def _roll_available_qty(execution_date: date) -> int:
    positions = await PositionSnapshot.filter(account_id=PAPER_ACCOUNT_ID, limit=None)
    updated = 0
    for pos in positions:
        if int(pos.qty) > 0 and int(pos.available_qty) < int(pos.qty):
            await pos.update({"available_qty": int(pos.qty), "snapshot_date": execution_date})
            updated += 1
    return updated


async def _configure_watchlist(client: httpx.AsyncClient) -> None:
    current = await client.get(f"{API_BASE}/trading/watchlists/{PAPER_ACCOUNT_ID}")
    current.raise_for_status()
    for item in current.json()["data"]["items"]:
        await client.delete(f"{API_BASE}/trading/watchlists/items/{item['id']}")
    for symbol, strategy_id in WATCHLIST_BINDINGS:
        resp = await client.post(
            f"{API_BASE}/trading/watchlists/{PAPER_ACCOUNT_ID}/items",
            json={
                "symbol": symbol,
                "target_weight": "0.1",
                "signal_config": {"strategy_id": strategy_id},
                "note": "paper-replay",
            },
        )
        resp.raise_for_status()
    print(f"已配置自选池：{len(WATCHLIST_BINDINGS)} 只标的，策略=ts_momentum_trend")


async def _fetch_approved_for_execution(client: httpx.AsyncClient, execution_date: date) -> list[dict]:
    resp = await client.get(
        f"{API_BASE}/trading/pre-orders",
        params={"account_id": PAPER_ACCOUNT_ID, "approval_status": "approved", "page_size": 500},
    )
    resp.raise_for_status()
    items = resp.json()["data"]["items"]
    return [
        item for item in items
        if item.get("status") == "approved" and item.get("execution_date") == execution_date.isoformat()
    ]


async def _submit_pre_order(client: httpx.AsyncClient, pre_order_id: int) -> dict:
    resp = await client.post(
        f"{API_BASE}/trading/pre-orders/{pre_order_id}/submit",
        json={"operator": OPERATOR},
    )
    body = resp.json()
    if resp.status_code != 200 or body.get("code") != 0:
        raise RuntimeError(body.get("message", resp.text))
    data = body["data"]
    if data.get("submitter") != "simulated":
        raise RuntimeError(f"paper 走了非模拟路径: submitter={data.get('submitter')}")
    return data


async def _run_decision(client: httpx.AsyncClient, signal_date: date, execution_date: date) -> dict:
    resp = await client.post(
        f"{API_BASE}/trading/accounts/{PAPER_ACCOUNT_ID}/decision-workflow/run",
        json={
            "signal_date": signal_date.isoformat(),
            "execution_date": execution_date.isoformat(),
            "min_confidence": MIN_CONFIDENCE,
            "max_selected": 10,
            "lookback_days": 120,
        },
    )
    body = resp.json()
    if resp.status_code != 200 or body.get("code") != 0:
        raise RuntimeError(body.get("message", resp.text))
    return body["data"]


async def _approve_pre_order(client: httpx.AsyncClient, pre_order_id: int) -> None:
    resp = await client.post(
        f"{API_BASE}/trading/approval/{pre_order_id}",
        json={"approved": True, "approved_by": OPERATOR, "comment": "paper-replay auto approve"},
    )
    body = resp.json()
    if resp.status_code != 200 or body.get("code") != 0:
        raise RuntimeError(body.get("message", resp.text))


async def run_replay() -> ReplayStats:
    stats = ReplayStats()
    trading_days = await _get_trading_days()
    stats.trading_days = len(trading_days)
    print(f"回放交易日: {len(trading_days)} 天 ({trading_days[0]} ~ {trading_days[-1]})")

    async with httpx.AsyncClient(timeout=180.0) as client:
        await _configure_watchlist(client)

        for idx, signal_date in enumerate(trading_days):
            day_log: dict = {"signal_date": signal_date.isoformat(), "executed": 0, "generated": 0}

            rolled = await _roll_available_qty(signal_date)
            if rolled:
                day_log["rolled_positions"] = rolled

            for item in await _fetch_approved_for_execution(client, signal_date):
                stats.executions_attempted += 1
                try:
                    result = await _submit_pre_order(client, item["id"])
                    if result["order"]["status"] == "filled":
                        stats.executions_filled += 1
                        day_log["executed"] += 1
                except Exception as exc:
                    stats.executions_failed += 1
                    stats.failures.append(f"exec {signal_date} po#{item['id']}: {exc}")

            if idx >= len(trading_days) - 1:
                stats.daily_log.append(day_log)
                continue

            execution_date = trading_days[idx + 1]
            stats.decision_runs += 1
            try:
                decision = await _run_decision(client, signal_date, execution_date)
            except Exception as exc:
                stats.failures.append(f"decision {signal_date}: {exc}")
                stats.daily_log.append(day_log)
                continue

            stats.signals_total += decision.get("signals_count", 0)
            pre_orders = decision.get("pre_orders") or []
            stats.pre_orders_generated += len(pre_orders)
            day_log.update({
                "generated": len(pre_orders),
                "signals": decision.get("signals_count", 0),
                "fusion": decision.get("fusion_count", 0),
                "execution_date": execution_date.isoformat(),
            })

            for po in pre_orders:
                try:
                    await _approve_pre_order(client, po["id"])
                    stats.pre_orders_approved += 1
                except Exception as exc:
                    stats.failures.append(f"approve {signal_date} po#{po['id']}: {exc}")

            stats.daily_log.append(day_log)
            if (idx + 1) % 5 == 0:
                print(
                    f"  进度 {idx + 1}/{len(trading_days)} "
                    f"T={signal_date} 生成={day_log['generated']} 成交={day_log['executed']}"
                )

    return stats


async def _print_final_report(stats: ReplayStats) -> dict:
    account = await TradingAccount.get(PAPER_ACCOUNT_ID)
    orders = await Order.filter(account_id=PAPER_ACCOUNT_ID, limit=None)
    trades = await Trade.filter(account_id=PAPER_ACCOUNT_ID, limit=None)
    snapshots = await AccountSnapshot.filter(
        account_id=PAPER_ACCOUNT_ID, limit=None, order_by=asc(AccountSnapshot.snapshot_date),
    )

    # 取每个标的最新持仓快照（按 snapshot_date 倒序去重）
    all_positions = await PositionSnapshot.filter(account_id=PAPER_ACCOUNT_ID, limit=None)
    latest_by_symbol: dict[str, PositionSnapshot] = {}
    for pos in sorted(all_positions, key=lambda p: p.snapshot_date, reverse=True):
        if pos.symbol not in latest_by_symbol and int(pos.qty) > 0:
            latest_by_symbol[pos.symbol] = pos
    active_positions = list(latest_by_symbol.values())

    initial = float(account.initial_capital)
    last_snapshot = snapshots[-1] if snapshots else None
    if last_snapshot:
        cash = float(last_snapshot.available_cash)
        market_value = float(last_snapshot.market_value)
        total_assets = float(last_snapshot.total_assets)
        cumulative_pnl = float(last_snapshot.cumulative_pnl)
    else:
        cash = float(account.available_cash)
        market_value = sum(float(p.market_value or 0) for p in active_positions)
        total_assets = cash + market_value
        cumulative_pnl = total_assets - initial

    report = {
        "replay_period": f"{REPLAY_START} ~ {REPLAY_END}",
        "stats": {
            "trading_days": stats.trading_days,
            "decision_runs": stats.decision_runs,
            "signals_total": stats.signals_total,
            "pre_orders_generated": stats.pre_orders_generated,
            "pre_orders_approved": stats.pre_orders_approved,
            "executions_attempted": stats.executions_attempted,
            "executions_filled": stats.executions_filled,
            "executions_failed": stats.executions_failed,
        },
        "account": {
            "initial_capital": initial,
            "available_cash": cash,
            "market_value": market_value,
            "total_assets": total_assets,
            "cumulative_pnl": cumulative_pnl,
            "cumulative_return_pct": round(cumulative_pnl / initial * 100, 4) if initial else 0,
        },
        "positions": [
            {
                "symbol": p.symbol,
                "qty": int(p.qty),
                "available_qty": int(p.available_qty),
                "cost_price": float(p.cost_price or 0),
                "market_value": float(p.market_value or 0),
                "unrealized_pnl": float(p.unrealized_pnl or 0),
            }
            for p in active_positions
        ],
        "orders_count": len(orders),
        "trades_count": len(trades),
        "snapshots_count": len(snapshots),
        "daily_pnl": [
            {
                "date": str(s.snapshot_date),
                "total_assets": float(s.total_assets),
                "daily_pnl": float(s.daily_pnl),
                "cumulative_pnl": float(s.cumulative_pnl),
            }
            for s in snapshots
        ],
        "failures": stats.failures[:30],
    }

    print("\n" + "=" * 60)
    print("模拟盘全链路回放报告")
    print("=" * 60)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


async def _print_analysis_report() -> None:
    """分析持仓收益与订单合理性。"""
    account = await TradingAccount.get(PAPER_ACCOUNT_ID)
    orders = await Order.filter(
        account_id=PAPER_ACCOUNT_ID,
        limit=None,
        order_by=[asc(Order.execution_date), asc(Order.id)],
    )
    pre_orders = await PreOrder.filter(
        instance_id__in=[i.id for i in await StrategyInstance.filter(account_id=PAPER_ACCOUNT_ID, limit=None)],
        signal_date__gte=REPLAY_START,
        limit=None,
    )
    snapshots = await AccountSnapshot.filter(
        account_id=PAPER_ACCOUNT_ID,
        limit=None,
        order_by=asc(AccountSnapshot.snapshot_date),
    )
    all_positions = await PositionSnapshot.filter(account_id=PAPER_ACCOUNT_ID, limit=None)
    latest_by_symbol: dict[str, PositionSnapshot] = {}
    for pos in sorted(all_positions, key=lambda p: p.snapshot_date, reverse=True):
        if pos.symbol not in latest_by_symbol and int(pos.qty) > 0:
            latest_by_symbol[pos.symbol] = pos

    initial = float(account.initial_capital)
    last_snap = snapshots[-1] if snapshots else None

    # 订单时间合理性：execution_date 应为 signal_date 的下一交易日
    time_issues: list[str] = []
    t_plus_one_ok = 0
    for order in orders:
        if order.signal_date and order.execution_date:
            if order.execution_date <= order.signal_date:
                time_issues.append(f"order#{order.id} exec={order.execution_date} <= signal={order.signal_date}")
            else:
                t_plus_one_ok += 1
        if order.created_at and order.execution_date:
            created_date = order.created_at.date() if hasattr(order.created_at, "date") else None
            if created_date and created_date != order.execution_date:
                time_issues.append(
                    f"order#{order.id} created_at={created_date} != execution_date={order.execution_date}"
                )

    pre_side = Counter(str(po.side) for po in pre_orders)
    buy_orders = sum(1 for o in orders if str(o.side) == "buy")
    sell_orders = sum(1 for o in orders if str(o.side) == "sell")

    daily_order_count = Counter(str(o.execution_date) for o in orders if o.execution_date)
    avg_daily = len(orders) / max(len(daily_order_count), 1)

    weight_deviations: list[float] = []
    for po in pre_orders:
        tw = float(po.target_weight or 0)
        cw = float(po.current_weight or 0)
        weight_deviations.append(abs(tw - cw))

    positions_analysis = []
    total_unrealized = 0.0
    total_market_value = 0.0
    for symbol, pos in sorted(latest_by_symbol.items()):
        mv = float(pos.market_value or 0)
        upnl = float(pos.unrealized_pnl or 0)
        total_unrealized += upnl
        total_market_value += mv
        positions_analysis.append({
            "symbol": symbol,
            "qty": int(pos.qty),
            "cost_price": round(float(pos.cost_price or 0), 4),
            "market_price": round(float(pos.market_price or 0), 4),
            "market_value": round(mv, 2),
            "weight_pct": round(float(pos.weight or 0) * 100, 2),
            "target_weight_pct": round(float(pos.target_weight or 0) * 100, 2),
            "unrealized_pnl": round(upnl, 2),
        })

    analysis = {
        "period": f"{REPLAY_START} ~ {REPLAY_END}",
        "account_summary": {
            "initial_capital": initial,
            "total_assets": round(float(last_snap.total_assets), 2) if last_snap else None,
            "cumulative_pnl": round(float(last_snap.cumulative_pnl), 2) if last_snap else None,
            "cumulative_return_pct": (
                round(float(last_snap.cumulative_pnl) / initial * 100, 4) if last_snap and initial else None
            ),
            "available_cash": round(float(last_snap.available_cash), 2) if last_snap else None,
            "market_value": round(float(last_snap.market_value), 2) if last_snap else None,
            "position_count": len(latest_by_symbol),
        },
        "order_rationality": {
            "total_orders": len(orders),
            "buy_orders": buy_orders,
            "sell_orders": sell_orders,
            "pre_order_sides": dict(pre_side),
            "avg_orders_per_execution_day": round(avg_daily, 2),
            "max_orders_one_day": max(daily_order_count.values()) if daily_order_count else 0,
            "t_plus_one_consistent": t_plus_one_ok,
            "time_issues_count": len(time_issues),
            "time_issues_sample": time_issues[:10],
            "pre_order_weight_deviation_avg_pct": (
                round(sum(weight_deviations) / len(weight_deviations) * 100, 2) if weight_deviations else 0
            ),
            "pre_order_weight_deviation_below_1pct": round(
                sum(1 for d in weight_deviations if d < 0.01) / len(weight_deviations) * 100, 1,
            ) if weight_deviations else 0,
            "add_reduce_ratio": round(
                (pre_side.get("add", 0) + pre_side.get("reduce", 0)) / max(len(pre_orders), 1) * 100, 1,
            ),
        },
        "positions": positions_analysis,
        "total_unrealized_pnl": round(total_unrealized, 2),
        "snapshots_trading_days": len(snapshots),
        "daily_pnl_last_5": [
            {
                "date": str(s.snapshot_date),
                "daily_pnl": round(float(s.daily_pnl), 2),
                "daily_return_pct": round(float(s.daily_return) * 100, 4),
                "total_assets": round(float(s.total_assets), 2),
            }
            for s in snapshots[-5:]
        ],
        "findings": [],
    }

    findings: list[str] = []
    if analysis["order_rationality"]["time_issues_count"] > 0:
        findings.append(f"存在 {analysis['order_rationality']['time_issues_count']} 条订单时间字段不一致")
    else:
        findings.append("订单 execution_date 均晚于 signal_date（T+1 语义正确），created_at 与 execution_date 对齐")

    if analysis["order_rationality"]["add_reduce_ratio"] > 60:
        findings.append(
            f"预订单中 ADD/REDUCE 占比 {analysis['order_rationality']['add_reduce_ratio']}% 偏高，"
            "主因决策流缺少 rebalance 阈值，权重漂移会触发日频微调"
        )

    if analysis["order_rationality"]["avg_orders_per_execution_day"] > 4:
        findings.append(
            f"日均成交 {analysis['order_rationality']['avg_orders_per_execution_day']} 笔，"
            "频率偏高；8 标的 × 日频决策 × 低 min_confidence(0.2) 叠加导致"
        )

    if last_snap and float(last_snap.total_assets) > 0:
        cash_ratio = float(last_snap.available_cash) / float(last_snap.total_assets)
        if cash_ratio > 0.5:
            findings.append(f"现金占比 {cash_ratio*100:.1f}% 偏高，仓位管理 max_total_weight=0.4~0.5 限制了总暴露")
        findings.append(
            f"累计收益 {analysis['account_summary']['cumulative_return_pct']}% "
            f"（{analysis['account_summary']['cumulative_pnl']} 元），"
            f"持仓 {len(latest_by_symbol)} 只，浮盈合计 {round(total_unrealized, 2)} 元"
        )

    analysis["findings"] = findings

    print("\n" + "=" * 60)
    print("持仓收益与订单合理性分析")
    print("=" * 60)
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


async def main() -> None:
    app = FastAPI()
    loader = DatasourceLoader(config_path=settings.APP.DB_CONFIG_PATH)
    register_datasource(
        app,
        datasource_config=loader.datasources,
        generate_schema=True,
        timescale_config=loader.timescale_config,
    )
    async with app.router.lifespan_context(app):
        await _reset_paper_account()
        stats = await run_replay()
        report = await _print_final_report(stats)
        await _print_analysis_report()

        if stats.pre_orders_generated == 0:
            raise SystemExit("回放失败：未生成任何预订单")
        if stats.executions_filled == 0:
            raise SystemExit("回放失败：未成交任何订单")
        if report["account"]["total_assets"] <= 0:
            raise SystemExit("回放失败：账户总资产异常")
        print("\n回放验收通过")


if __name__ == "__main__":
    asyncio.run(main())
