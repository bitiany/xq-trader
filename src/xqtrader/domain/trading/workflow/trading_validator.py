"""交易校验器 — 预订单/订单状态校验与模拟撮合滑点辅助。

从 PreOrderExecutionWorkflowService 抽离的校验/辅助职责：
- 预订单可下单性校验（账户、审批、风控、reduce_only 等）
- Kill Switch 紧急全平预订单识别
- 模拟撮合滑点配置抽取与应用（percent/tick/atr 三种模式）
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from framework.commons.exceptions import BusinessException
from xqtrader.domain.trading.enums import (
    AccountType,
    ApprovalStatus,
    BrokerType,
    OrderSide,
    OrderType,
    PreOrderSide,
    PreOrderStatus,
)
from xqtrader.domain.trading.models.account import TradingAccount
from xqtrader.domain.trading.models.order import Order, PreOrder
from xqtrader.domain.trading.workflow.order_type_converter import OrderTypeConverter


class TradingValidator:
    """预订单/订单状态校验与模拟撮合滑点辅助。"""

    @classmethod
    def validate_pre_order(cls, pre_order: PreOrder, account: TradingAccount) -> None:
        if not account.is_enabled:
            raise BusinessException(message=f"账户已禁用: {account.id}")
        if account.account_type not in {AccountType.LIVE, AccountType.PAPER}:
            raise BusinessException(message=f"账户类型不合法: {account.account_type}")
        if account.account_type == AccountType.LIVE and account.broker_type != BrokerType.QMT:
            raise BusinessException(message=f"实盘账户仅支持QMT下单: {account.broker_type}")
        if pre_order.approval_status != ApprovalStatus.APPROVED:
            raise BusinessException(message=f"预订单未审批通过: {pre_order.id}")
        if pre_order.status != PreOrderStatus.APPROVED:
            raise BusinessException(message=f"预订单状态为 {pre_order.status}，不可下单")
        if pre_order.risk_check_passed is not True:
            raise BusinessException(message=f"预订单风控未通过: {pre_order.id}")
        if int(pre_order.target_qty or 0) <= 0:
            raise BusinessException(message=f"预订单目标数量必须大于0: {pre_order.id}")
        if pre_order.order_type == OrderType.LIMIT and pre_order.limit_price is None:
            raise BusinessException(message=f"限价预订单缺少价格: {pre_order.id}")
        if account.reduce_only and pre_order.side in {PreOrderSide.OPEN, PreOrderSide.ADD}:
            raise BusinessException(message=f"账户处于仅减仓状态，禁止开仓/加仓: {account.id}")

    @staticmethod
    def is_kill_switch_pre_order(pre_order: PreOrder | None) -> bool:
        """识别 Kill Switch 紧急全平生成的 close 预订单。"""
        if pre_order is None:
            return False
        return pre_order.sizing_strategy == "kill_switch"

    @staticmethod
    def extract_slippage_config(pre_order: PreOrder | None) -> dict[str, Any]:
        if pre_order is None or not isinstance(pre_order.risk_check_detail, dict):
            return {"type": "none"}
        execution_config = pre_order.risk_check_detail.get("approval_execution")
        if not isinstance(execution_config, dict):
            return {"type": "none"}
        slippage = execution_config.get("slippage")
        if not isinstance(slippage, dict):
            return {"type": "none"}
        return slippage

    @staticmethod
    def apply_simulated_slippage(
        order: Order,
        base_price: Decimal,
        slippage: dict[str, Any],
    ) -> Decimal:
        slippage_type = str(slippage.get("type") or "none")
        direction = Decimal("1") if order.side == OrderSide.BUY else Decimal("-1")
        if slippage_type == "percent":
            rate = Decimal(str(slippage.get("rate") or 0))
            return OrderTypeConverter.quantize_price(base_price * (Decimal("1") + direction * rate))
        if slippage_type == "tick":
            ticks = Decimal(str(slippage.get("ticks") or 0))
            tick_size = Decimal(str(slippage.get("tick_size") or "0.01"))
            return OrderTypeConverter.quantize_price(base_price + direction * ticks * tick_size)
        if slippage_type == "atr":
            atr = Decimal(str(slippage.get("atr") or 0))
            multiplier = Decimal(str(slippage.get("multiplier") or 0))
            return OrderTypeConverter.quantize_price(base_price + direction * atr * multiplier)
        return base_price
