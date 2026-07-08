"""模拟撮合服务 — 预订单在 PAPER 账户下的本地撮合与持仓/账户快照刷新。

从 PreOrderExecutionWorkflowService 抽离的模拟撮合职责：
- 订单提交：填充成交回报、生成 Trade、刷新 PositionSnapshot/AccountSnapshot
- 滑点模拟：基于预订单配置的 percent/tick/atr 模式调整成交价
- 持仓/账户刷新：成交后同步持仓 qty/cost_price、账户总资产/盈亏/权重

依赖 PreOrderExecutionWorkflowService 的订单状态变更能力（get_order_for_submit /
mark_submitted / append_event），通过构造注入避免循环依赖与重复创建。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from framework.commons.exceptions import BusinessException, WorkflowConfigError
from framework.commons.time_util import market_open_shanghai, now_shanghai
from framework.dal.transaction.transactional import transactional
from xqtrader.domain.market.models.candlestick import CandlestickDaily
from xqtrader.domain.trading.enums import (
    AccountType,
    OrderEventType,
    OrderSide,
    OrderStatus,
    OrderType,
)
from xqtrader.domain.trading.models.account import AccountSnapshot, TradingAccount
from xqtrader.domain.trading.models.order import Order, PreOrder, Trade
from xqtrader.domain.trading.models.position import PositionSnapshot
from xqtrader.domain.trading.workflow.order_type_converter import OrderTypeConverter
from xqtrader.domain.trading.workflow.trading_serializer import TradingSerializer
from xqtrader.domain.trading.workflow.trading_validator import TradingValidator

if TYPE_CHECKING:
    from xqtrader.domain.trading.workflow.execution_service import (
        PreOrderExecutionWorkflowService,
    )


class SimulatedMatchingService:
    """模拟撮合服务：负责 PAPER 账户下的本地撮合与持仓/账户快照刷新。"""

    def __init__(self, execution_service: PreOrderExecutionWorkflowService) -> None:
        self._execution_service = execution_service

    @transactional(bind_key="trading")
    async def submit_simulated_order(
        self,
        order_id: int,
        operator: str,
    ) -> dict[str, Any]:
        order = await self._execution_service.get_order_for_submit(order_id)
        if order.account_id is None:
            raise BusinessException(message=f"模拟订单缺少账户ID: {order.id}")
        account = await TradingAccount.get(order.account_id)
        if account is None:
            raise WorkflowConfigError(f"TradingAccount not found: {order.account_id}")
        if account.account_type != AccountType.PAPER:
            raise BusinessException(message=f"模拟提交仅支持模拟盘账户: {account.id}")
        pre_order = await PreOrder.get(order.pre_order_id) if order.pre_order_id is not None else None
        fill_context = await self._build_simulated_fill_context(order, account, pre_order)
        broker_order_id = f"SIM-{order.platform_order_id}"
        await self._execution_service.mark_submitted(
            order=order,
            broker_order_id=broker_order_id,
            event_data={
                "submitter": "simulated",
                "base_price": TradingSerializer.decimal_to_str(fill_context["base_price"]),
                "filled_price": TradingSerializer.decimal_to_str(fill_context["filled_price"]),
                "slippage": fill_context["slippage"],
            },
            operator=operator,
        )
        trade = await self._fill_simulated_order(order, account, pre_order, fill_context, operator)
        return {
            "order": TradingSerializer.serialize_order(order),
            "submitter": "simulated",
            "broker_order_id": broker_order_id,
            "trade": TradingSerializer.serialize_trade(trade),
        }

    async def _build_simulated_fill_context(
        self,
        order: Order,
        account: TradingAccount,
        pre_order: PreOrder | None,
    ) -> dict[str, Any]:
        base_price = await self._resolve_simulated_base_price(order)
        slippage = TradingValidator.extract_slippage_config(pre_order)
        filled_price = TradingValidator.apply_simulated_slippage(order, base_price, slippage)
        if filled_price <= 0:
            raise BusinessException(message=f"模拟成交价格必须大于0: {order.id}")
        # Kill Switch 紧急全平绕过 T+1 available_qty 检查（按 qty 强制平仓）
        is_kill_switch = TradingValidator.is_kill_switch_pre_order(pre_order)
        if order.side == OrderSide.SELL and not is_kill_switch:
            position = await self._load_latest_position(order)
            available_qty = int(position.available_qty) if position is not None else 0
            if available_qty < order.order_qty:
                raise BusinessException(message=f"模拟卖出可用持仓不足: {order.symbol}")
        amount = OrderTypeConverter.quantize_money(filled_price * Decimal(order.order_qty))
        broker_config = getattr(account, "broker_config", None) or {}
        commission_rate = OrderTypeConverter.decimal_config(broker_config, "commission_rate", Decimal("0.0003"))
        stamp_tax_rate = OrderTypeConverter.decimal_config(broker_config, "stamp_tax_rate", Decimal("0.001"))
        commission = OrderTypeConverter.quantize_money(amount * commission_rate)
        tax = (
            OrderTypeConverter.quantize_money(amount * stamp_tax_rate)
            if order.side == OrderSide.SELL
            else Decimal("0.0000")
        )
        cash_delta = -amount - commission if order.side == OrderSide.BUY else amount - commission - tax
        available_cash = Decimal(str(account.available_cash))
        if available_cash + cash_delta < 0:
            raise BusinessException(message=f"模拟买入可用资金不足: {order.symbol}")
        return {
            "base_price": base_price,
            "filled_price": filled_price,
            "filled_amount": amount,
            "commission": commission,
            "tax": tax,
            "cash_delta": cash_delta,
            "slippage": slippage,
        }

    async def _fill_simulated_order(
        self,
        order: Order,
        account: TradingAccount,
        pre_order: PreOrder | None,
        fill_context: dict[str, Any],
        operator: str,
    ) -> Trade:
        trade_time = self._resolve_simulated_trade_time(order)
        filled_price = fill_context["filled_price"]
        filled_amount = fill_context["filled_amount"]
        commission = fill_context["commission"]
        tax = fill_context["tax"]
        cash_delta = fill_context["cash_delta"]
        await account.update({
            "available_cash": OrderTypeConverter.quantize_money(Decimal(str(account.available_cash)) + cash_delta),
            "frozen_cash": OrderTypeConverter.quantize_money(Decimal(str(account.frozen_cash))),
        })
        trade = await Trade.create(
            order_id=order.id,
            account_id=order.account_id,
            symbol=order.symbol,
            side=order.side,
            filled_price=filled_price,
            filled_qty=order.order_qty,
            filled_amount=filled_amount,
            commission=commission,
            tax=tax,
            trade_time=trade_time,
            broker_trade_id=f"SIMT-{order.platform_order_id}",
        )
        await order.update({
            "status": OrderStatus.FILLED,
            "filled_price": filled_price,
            "filled_qty": order.order_qty,
        })
        position = await self._update_position_after_fill(order, pre_order, fill_context, trade_time)
        snapshot_date = order.execution_date or trade_time.date()
        snapshot = await self._refresh_account_snapshot(account, snapshot_date, trade_time)
        await self._refresh_position_weight(position, pre_order, snapshot)
        await self._execution_service.append_event(
            order.id,
            OrderEventType.FILLED,
            {
                "trade_id": trade.id,
                "filled_price": TradingSerializer.decimal_to_str(filled_price),
                "filled_qty": order.order_qty,
                "filled_amount": TradingSerializer.decimal_to_str(filled_amount),
                "commission": TradingSerializer.decimal_to_str(commission),
                "tax": TradingSerializer.decimal_to_str(tax),
            },
            operator,
        )
        return trade

    @staticmethod
    def _resolve_simulated_trade_time(order: Order) -> datetime:
        if order.execution_date is not None:
            return market_open_shanghai(order.execution_date)
        return now_shanghai()

    async def _resolve_simulated_base_price(self, order: Order) -> Decimal:
        if order.order_type == OrderType.LIMIT:
            if order.order_price is None:
                raise BusinessException(message="模拟限价订单缺少委托价格")
            return OrderTypeConverter.quantize_price(Decimal(str(order.order_price)))
        # 市价单：优先用持仓的最新市值，其次回退到最近收盘价（用于买入新标的）
        position = await self._load_latest_position(order)
        if position is not None:
            if position.market_price is not None and Decimal(str(position.market_price)) > 0:
                return OrderTypeConverter.quantize_price(Decimal(str(position.market_price)))
            if position.cost_price is not None and Decimal(str(position.cost_price)) > 0:
                return OrderTypeConverter.quantize_price(Decimal(str(position.cost_price)))
        ref_date = order.execution_date or now_shanghai().date()
        bars = await CandlestickDaily.filter(
            symbol=order.symbol,
            trade_date__lte=ref_date,
            limit=1,
            order_by=CandlestickDaily.trade_date.desc(),
        )
        if bars and bars[0].close and float(bars[0].close) > 0:
            return OrderTypeConverter.quantize_price(Decimal(str(bars[0].close)))
        raise BusinessException(message=f"模拟市价订单缺少可用成交价格: {order.symbol}")

    async def _load_latest_position(self, order: Order) -> PositionSnapshot | None:
        positions = await PositionSnapshot.filter(
            account_id=order.account_id,
            instance_id=order.instance_id,
            symbol=order.symbol,
            limit=1,
            order_by=PositionSnapshot.snapshot_date.desc(),
        )
        return positions[0] if positions else None

    async def _update_position_after_fill(
        self,
        order: Order,
        pre_order: PreOrder | None,
        fill_context: dict[str, Any],
        trade_time: datetime,
    ) -> PositionSnapshot:
        position = await self._load_latest_position(order)
        previous_qty = int(position.qty) if position is not None else 0
        previous_available_qty = int(position.available_qty) if position is not None else 0
        previous_cost_price = (
            Decimal(str(position.cost_price))
            if position is not None and position.cost_price is not None
            else fill_context["filled_price"]
        )
        filled_qty = int(order.order_qty)
        filled_price = fill_context["filled_price"]
        filled_amount = fill_context["filled_amount"]
        if order.side == OrderSide.BUY:
            qty = previous_qty + filled_qty
            available_qty = previous_available_qty
            cost_amount = previous_cost_price * Decimal(previous_qty) + filled_amount
            cost_price = OrderTypeConverter.quantize_price(cost_amount / Decimal(qty)) if qty > 0 else None
        else:
            qty = previous_qty - filled_qty
            available_qty = max(previous_available_qty - filled_qty, 0)
            cost_price = previous_cost_price if qty > 0 else None
        market_value = OrderTypeConverter.quantize_money(filled_price * Decimal(qty)) if qty > 0 else Decimal("0.0000")
        target_weight = (
            Decimal(str(pre_order.target_weight))
            if pre_order and pre_order.target_weight is not None
            else None
        )
        unrealized_pnl = (
            OrderTypeConverter.quantize_money((filled_price - cost_price) * Decimal(qty))
            if cost_price
            else Decimal("0.0000")
        )
        data = {
            "account_id": order.account_id,
            "instance_id": order.instance_id,
            "symbol": order.symbol,
            "snapshot_date": order.execution_date or trade_time.date(),
            "qty": qty,
            "available_qty": available_qty,
            "cost_price": cost_price,
            "market_price": filled_price,
            "market_value": market_value,
            "weight": None,
            "target_weight": target_weight,
            "weight_deviation": None,
            "unrealized_pnl": unrealized_pnl,
            "daily_pnl": Decimal("0.0000"),
            "snapshot_time": trade_time,
            "extra": {
                "source": "simulated_execution",
                "order_id": order.id,
                "pre_order_id": order.pre_order_id,
            },
        }
        snapshot = await PositionSnapshot.get_one_or_none(
            account_id=order.account_id,
            instance_id=order.instance_id,
            symbol=order.symbol,
            snapshot_date=data["snapshot_date"],
        )
        if snapshot is None:
            return await PositionSnapshot.create(**data)
        await snapshot.update(data)
        return snapshot

    async def _refresh_account_snapshot(
        self,
        account: TradingAccount,
        snapshot_date: date,
        snapshot_time: datetime,
    ) -> AccountSnapshot:
        latest_positions = await self._load_latest_account_positions(account.id)
        active_positions = [position for position in latest_positions if int(position.qty) > 0]
        market_value = OrderTypeConverter.quantize_money(sum(
            (Decimal(str(position.market_value)) for position in active_positions if position.market_value is not None),
            Decimal("0"),
        ))
        available_cash = OrderTypeConverter.quantize_money(Decimal(str(account.available_cash)))
        frozen_cash = OrderTypeConverter.quantize_money(Decimal(str(account.frozen_cash)))
        total_assets = OrderTypeConverter.quantize_money(available_cash + frozen_cash + market_value)
        initial_capital = Decimal(str(account.initial_capital))
        cumulative_pnl = OrderTypeConverter.quantize_money(total_assets - initial_capital)
        # 当日盈亏 = 今日总资产 - 上一交易日总资产；若无历史快照则等于累计盈亏
        prev_snapshot = await self._load_previous_account_snapshot(account.id, snapshot_date)
        if prev_snapshot is not None:
            prev_total_assets = Decimal(str(prev_snapshot.total_assets))
            daily_pnl = OrderTypeConverter.quantize_money(total_assets - prev_total_assets)
            daily_return = (
                OrderTypeConverter.quantize_weight(daily_pnl / prev_total_assets)
                if prev_total_assets > 0 else Decimal("0")
            )
        else:
            daily_pnl = cumulative_pnl
            daily_return = (
                OrderTypeConverter.quantize_weight(cumulative_pnl / initial_capital)
                if initial_capital > 0 else Decimal("0")
            )
        data = {
            "account_id": account.id,
            "snapshot_date": snapshot_date,
            "total_assets": total_assets,
            "market_value": market_value,
            "available_cash": available_cash,
            "frozen_cash": frozen_cash,
            "daily_pnl": daily_pnl,
            "cumulative_pnl": cumulative_pnl,
            "daily_return": daily_return,
            "position_count": len(active_positions),
            "snapshot_time": snapshot_time,
        }
        snapshot = await AccountSnapshot.get_one_or_none(account_id=account.id, snapshot_date=snapshot_date)
        if snapshot is None:
            return await AccountSnapshot.create(**data)
        await snapshot.update(data)
        return snapshot

    @staticmethod
    async def _load_previous_account_snapshot(
        account_id: int,
        current_date: date,
    ) -> AccountSnapshot | None:
        prev_snapshots = await AccountSnapshot.filter(
            account_id=account_id,
            snapshot_date__lt=current_date,
            limit=1,
            order_by=AccountSnapshot.snapshot_date.desc(),
        )
        return prev_snapshots[0] if prev_snapshots else None

    @staticmethod
    async def _load_latest_account_positions(account_id: int) -> list[PositionSnapshot]:
        positions = await PositionSnapshot.filter(
            account_id=account_id,
            limit=None,
            order_by=PositionSnapshot.snapshot_date.desc(),
        )
        latest: dict[tuple[int | None, str], PositionSnapshot] = {}
        for position in positions:
            key = (position.instance_id, position.symbol)
            if key not in latest:
                latest[key] = position
        return list(latest.values())

    async def _refresh_position_weight(
        self,
        position: PositionSnapshot,
        pre_order: PreOrder | None,
        snapshot: AccountSnapshot,
    ) -> None:
        total_assets = Decimal(str(snapshot.total_assets))
        market_value = Decimal(str(position.market_value or 0))
        weight = OrderTypeConverter.quantize_weight(market_value / total_assets) if total_assets > 0 else Decimal("0")
        target_weight = (
            Decimal(str(pre_order.target_weight))
            if pre_order and pre_order.target_weight is not None
            else position.target_weight
        )
        target = Decimal(str(target_weight)) if target_weight is not None else None
        await position.update({
            "weight": weight,
            "target_weight": target,
            "weight_deviation": OrderTypeConverter.quantize_weight(weight - target) if target is not None else None,
        })
