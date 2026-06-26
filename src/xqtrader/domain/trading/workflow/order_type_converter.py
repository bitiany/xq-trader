"""交易类型转换器 — 预订单/订单方向与 QMT 委托类型互转，并集中量化配置。

从 PreOrderExecutionWorkflowService 抽离的转换/量化职责：
- 预订单方向 → 订单方向、订单方向 → QMT 委托类型
- 价格/金额/权重 Decimal 量化（统一精度配置）
- broker_config Decimal 配置读取
- 订单结果 dict 组装（依赖 TradingSerializer）
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from framework.commons.exceptions import BusinessException
from framework.commons.time_util import now_shanghai
from xqtrader.domain.trading.enums import (
    AccountType,
    OrderSide,
    OrderType,
    PreOrderSide,
)
from xqtrader.domain.trading.models.account import TradingAccount
from xqtrader.domain.trading.models.order import Order
from xqtrader.domain.trading.workflow.trading_serializer import TradingSerializer


class QmtOrderConstants:
    """QMT 委托类型常量（与 xtquant xtconstant 对齐）。"""

    STOCK_BUY = 23
    STOCK_SELL = 24
    FIX_PRICE = 11
    LATEST_PRICE = 5


class OrderTypeConverter:
    """预订单/订单类型转换与 Decimal 量化（无状态工具类，全部 staticmethod/classmethod）。"""

    _PRICE_QUANT = Decimal("0.0001")
    _WEIGHT_QUANT = Decimal("0.000001")

    @staticmethod
    def to_order_side(pre_order_side: str) -> str:
        if pre_order_side in {PreOrderSide.OPEN, PreOrderSide.ADD}:
            return OrderSide.BUY
        if pre_order_side in {PreOrderSide.REDUCE, PreOrderSide.CLOSE}:
            return OrderSide.SELL
        raise BusinessException(message=f"预订单方向不合法: {pre_order_side}")

    @staticmethod
    def to_qmt_order_type(order_side: str) -> int:
        if order_side == OrderSide.BUY:
            return QmtOrderConstants.STOCK_BUY
        if order_side == OrderSide.SELL:
            return QmtOrderConstants.STOCK_SELL
        raise BusinessException(message=f"订单方向不合法: {order_side}")

    @staticmethod
    def to_qmt_price_type(order_type: str) -> int:
        if order_type == OrderType.LIMIT:
            return QmtOrderConstants.FIX_PRICE
        if order_type == OrderType.MARKET:
            return QmtOrderConstants.LATEST_PRICE
        raise BusinessException(message=f"订单类型不合法: {order_type}")

    @staticmethod
    def to_qmt_price(order_price: Decimal | None, order_type: str) -> float:
        if order_type == OrderType.MARKET:
            return 0.0
        if order_price is None:
            raise BusinessException(message="限价订单缺少委托价格")
        return float(order_price)

    @staticmethod
    def resolve_submitter(account: TradingAccount) -> str:
        if account.account_type == AccountType.LIVE:
            return "qmt"
        return "simulated"

    @staticmethod
    def build_order_result(order: Order, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "order": TradingSerializer.serialize_order(order),
            "pre_order_id": context["pre_order_id"],
            "account_type": context["account_type"],
            "broker_type": context["broker_type"],
            "created_at": now_shanghai().isoformat(),
        }

    @classmethod
    def quantize_price(cls, value: Decimal) -> Decimal:
        return value.quantize(cls._PRICE_QUANT)

    @classmethod
    def quantize_money(cls, value: Decimal) -> Decimal:
        return value.quantize(cls._PRICE_QUANT)

    @classmethod
    def quantize_weight(cls, value: Decimal) -> Decimal:
        return value.quantize(cls._WEIGHT_QUANT)

    @staticmethod
    def decimal_config(config: dict[str, Any], key: str, default: Decimal) -> Decimal:
        value = config.get(key)
        if value is None:
            return default
        return Decimal(str(value))
