"""交易实体序列化器 — 将 ORM 对象转换为 API 可返回的 dict。

从 PreOrderExecutionWorkflowService 抽离的序列化职责：日期/Decimal 字段统一转字符串，
避免 JSON 序列化精度丢失；UUID 统一转字符串。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from xqtrader.domain.trading.models.account import TradingAccount
from xqtrader.domain.trading.models.instance import StrategyInstance
from xqtrader.domain.trading.models.order import Order, PreOrder, Trade


class TradingSerializer:
    """交易实体序列化器（无状态工具类，全部 staticmethod）。"""

    @staticmethod
    def serialize_order(order: Order) -> dict[str, Any]:
        data = order.to_dict()
        data["platform_order_id"] = str(order.platform_order_id) if order.platform_order_id else None
        data["order_price"] = TradingSerializer.decimal_to_str(order.order_price)
        data["filled_price"] = TradingSerializer.decimal_to_str(order.filled_price)
        data["signal_date"] = TradingSerializer.date_to_str(order.signal_date)
        data["execution_date"] = TradingSerializer.date_to_str(order.execution_date)
        data["created_at"] = TradingSerializer.datetime_to_str(order.created_at)
        data["updated_at"] = TradingSerializer.datetime_to_str(order.updated_at)
        return data

    @staticmethod
    def serialize_trade(trade: Trade) -> dict[str, Any]:
        data = trade.to_dict()
        data["filled_price"] = TradingSerializer.decimal_to_str(trade.filled_price)
        data["filled_amount"] = TradingSerializer.decimal_to_str(trade.filled_amount)
        data["commission"] = TradingSerializer.decimal_to_str(trade.commission)
        data["tax"] = TradingSerializer.decimal_to_str(trade.tax)
        data["trade_time"] = TradingSerializer.datetime_to_str(trade.trade_time)
        data["created_at"] = TradingSerializer.datetime_to_str(trade.created_at)
        return data

    @staticmethod
    def serialize_pre_order(pre_order: PreOrder) -> dict[str, Any]:
        data = pre_order.to_dict()
        data["signal_date"] = TradingSerializer.date_to_str(pre_order.signal_date)
        data["execution_date"] = TradingSerializer.date_to_str(pre_order.execution_date)
        data["limit_price"] = TradingSerializer.decimal_to_str(pre_order.limit_price)
        data["approved_at"] = TradingSerializer.datetime_to_str(pre_order.approved_at)
        data["expired_at"] = TradingSerializer.datetime_to_str(pre_order.expired_at)
        data["created_at"] = TradingSerializer.datetime_to_str(pre_order.created_at)
        data["updated_at"] = TradingSerializer.datetime_to_str(pre_order.updated_at)
        return data

    @staticmethod
    def serialize_account(account: TradingAccount) -> dict[str, Any]:
        data = account.to_dict()
        data["initial_capital"] = TradingSerializer.decimal_to_str(account.initial_capital)
        data["available_cash"] = TradingSerializer.decimal_to_str(account.available_cash)
        data["frozen_cash"] = TradingSerializer.decimal_to_str(account.frozen_cash)
        data["created_at"] = TradingSerializer.datetime_to_str(account.created_at)
        data["updated_at"] = TradingSerializer.datetime_to_str(account.updated_at)
        return data

    @staticmethod
    def serialize_instance(instance: StrategyInstance) -> dict[str, Any]:
        data = instance.to_dict()
        data["started_at"] = TradingSerializer.datetime_to_str(instance.started_at)
        data["stopped_at"] = TradingSerializer.datetime_to_str(instance.stopped_at)
        data["created_at"] = TradingSerializer.datetime_to_str(instance.created_at)
        data["updated_at"] = TradingSerializer.datetime_to_str(instance.updated_at)
        return data

    @staticmethod
    def decimal_to_str(value: Decimal | None) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def date_to_str(value: date | None) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def datetime_to_str(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None
