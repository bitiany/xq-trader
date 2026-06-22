"""券商适配器协议 — 环境无关的券商接口抽象。

定义统一的券商交互接口，三环境各自实现:
  - BacktestBrokerAdapter: 包装 backtrader broker（同步，回测）
  - PaperBrokerAdapter: 模拟盘 broker（异步，模拟盘）
  - LiveBrokerAdapter: 实盘 QMT broker（异步，实盘）

设计原则:
  - Protocol 仅定义接口与数据类型，不依赖任何具体 broker 库
  - 数据类型与现有模型对齐（Order/Position/Account），但为轻量 dataclass
  - 回测适配器同步调用，模拟盘/实盘适配器异步调用
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .enums import OrderType


@dataclass
class OrderRequest:
    """订单请求 — 环境无关的订单提交请求。

    Attributes:
        symbol: 证券代码
        side: 买卖方向 — buy/sell
        qty: 委托数量（回测支持小数，实盘为整手）
        order_type: 订单类型 — market/limit
        price: 限价（仅 limit 订单需要）
    """

    symbol: str
    side: str
    qty: float
    order_type: str = OrderType.MARKET
    price: float | None = None


@dataclass
class OrderResponse:
    """订单响应 — 订单提交后的即时响应。

    Attributes:
        order_id: 券商委托号（回测内为 backtrader order ref）
        status: 订单状态 — submitted/filled/rejected/cancelled
        filled_qty: 已成交数量
        avg_price: 成交均价
        message: 附加信息（拒绝原因等）
    """

    order_id: str
    status: str
    filled_qty: float = 0.0
    avg_price: float = 0.0
    message: str = ""


@dataclass
class BrokerPosition:
    """券商持仓 — 单标的持仓信息。

    Attributes:
        symbol: 证券代码
        qty: 持仓数量（正=多头，负=空头）
        avg_price: 持仓均价
        market_value: 持仓市值
        current_price: 当前价格
    """

    symbol: str
    qty: float = 0.0
    avg_price: float = 0.0
    market_value: float = 0.0
    current_price: float = 0.0


@dataclass
class AccountInfo:
    """账户信息 — 资金与持仓概览。

    Attributes:
        cash: 可用现金
        total_value: 总资产（现金 + 持仓市值）
        positions_value: 持仓市值
        frozen_cash: 冻结资金
    """

    cash: float = 0.0
    total_value: float = 0.0
    positions_value: float = 0.0
    frozen_cash: float = 0.0


@dataclass
class BrokerCapability:
    """券商能力描述 — 声明适配器支持的功能。

    用于运行时能力检查，避免调用不支持的方法。
    """

    supports_limit: bool = True
    supports_short: bool = False
    supports_fractional_shares: bool = False
    min_order_qty: float = 100.0
    price_tick: float = 0.01
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.001  # 卖出印花税


@runtime_checkable
class BrokerAdapter(Protocol):
    """券商适配器协议 — 环境无关的券商接口抽象。

    三环境实现:
      - BacktestBrokerAdapter: 包装 backtrader broker（同步）
      - PaperBrokerAdapter: 模拟盘 broker（异步包装）
      - LiveBrokerAdapter: 实盘 QMT broker（异步包装）

    用法:
        # 回测内（XqTraderStrategy.next()）
        adapter: BrokerAdapter = backtest_adapter
        response = adapter.submit_order(OrderRequest(...))

        # 模拟盘/实盘决策流
        adapter: BrokerAdapter = paper_adapter
        response = await adapter.submit_order_async(OrderRequest(...))
    """

    @property
    def broker_type(self) -> str:
        """券商类型 — backtest/simulated/qmt。"""
        ...

    @property
    def capability(self) -> BrokerCapability:
        """券商能力描述。"""
        ...

    def submit_order(self, request: OrderRequest) -> OrderResponse:
        """提交订单。

        Args:
            request: 订单请求

        Returns:
            订单响应（状态为 submitted 表示已接受，filled 表示已成交）
        """
        ...

    def cancel_order(self, order_id: str) -> bool:
        """撤销订单。

        Args:
            order_id: 券商委托号

        Returns:
            是否成功撤销
        """
        ...

    def get_position(self, symbol: str) -> BrokerPosition:
        """获取单个标的持仓。

        Args:
            symbol: 证券代码

        Returns:
            持仓信息（无持仓时 qty=0）
        """
        ...

    def get_positions(self) -> dict[str, BrokerPosition]:
        """获取所有持仓。

        Returns:
            {symbol: BrokerPosition} 仅有持仓的标的
        """
        ...

    def get_account(self) -> AccountInfo:
        """获取账户信息。

        Returns:
            账户资金与持仓概览
        """
        ...
