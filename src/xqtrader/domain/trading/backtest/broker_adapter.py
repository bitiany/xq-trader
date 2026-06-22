"""回测券商适配器 — 包装 backtrader broker 实现 BrokerAdapter 协议。

在 XqTraderStrategy.next() 内使用，将目标仓位转换为 backtrader 订单。
通过 register_data() 注册 symbol → DataFeed 映射后，即可提交订单、查询持仓。

设计原则:
  - 实现 BrokerAdapter 协议（submit_order/cancel_order/get_position/...）
  - 额外提供 order_target_percent() 便捷方法（backtrader 特有）
  - backtrader 对象通过 Any 引用，避免模块级导入 backtrader
"""

from __future__ import annotations

import math
from typing import Any, ClassVar

from framework.commons.logger import get_logger

from ..broker import (
    AccountInfo,
    BrokerCapability,
    BrokerPosition,
    OrderRequest,
    OrderResponse,
)
from ..enums import BrokerType, OrderSide

logger = get_logger(__name__)


class BacktestBrokerAdapter:
    """回测券商适配器 — 包装 backtrader broker。

    用法:
        adapter = BacktestBrokerAdapter(strategy)
        adapter.register_data("000001.SZ", data_feed)
        # 按目标百分比下单
        adapter.order_target_percent("000001.SZ", 0.10)
        # 或按数量下单
        adapter.submit_order(OrderRequest(symbol="000001.SZ", side="buy", qty=100))
        # 查询持仓与账户
        positions = adapter.get_positions()
        account = adapter.get_account()
    """

    # 类级缓存 backtrader Order.Limit，避免重复导入
    _limit_exectype: ClassVar[Any] = None

    def __init__(self, strategy: Any) -> None:
        """初始化。

        Args:
            strategy: backtrader Strategy 实例（XqTraderStrategy）
        """
        self._strategy = strategy
        self._broker = strategy.broker
        self._symbol_to_data: dict[str, Any] = {}
        self._capability = BrokerCapability(
            supports_limit=True,
            supports_short=False,
            supports_fractional_shares=True,  # backtrader 支持小数股
            min_order_qty=0.0,
            price_tick=0.01,
            commission_rate=0.0003,
            stamp_tax_rate=0.001,
        )

    @property
    def broker_type(self) -> str:
        """券商类型 — backtest。"""
        return BrokerType.BACKTEST

    @property
    def capability(self) -> BrokerCapability:
        """券商能力描述。"""
        return self._capability

    def register_data(self, symbol: str, data: Any) -> None:
        """注册标的到 backtrader DataFeed 的映射。

        Args:
            symbol: 证券代码
            data: backtrader DataFeed 实例
        """
        self._symbol_to_data[symbol] = data

    def submit_order(self, request: OrderRequest) -> OrderResponse:
        """提交订单到 backtrader。"""
        data = self._symbol_to_data.get(request.symbol)
        if data is None:
            return OrderResponse(
                order_id="",
                status="rejected",
                message=f"未注册标的数据: {request.symbol}",
            )

        kwargs: dict[str, Any] = {"data": data, "size": request.qty}
        if request.order_type == "limit" and request.price is not None:
            kwargs["price"] = request.price
            kwargs["exectype"] = self._get_limit_exectype()

        try:
            if request.side == OrderSide.BUY:
                order = self._strategy.buy(**kwargs)
            elif request.side == OrderSide.SELL:
                order = self._strategy.sell(**kwargs)
            else:
                return OrderResponse(
                    order_id="",
                    status="rejected",
                    message=f"未知订单方向: {request.side}",
                )
        except Exception as e:
            logger.error(
                f"回测下单失败: symbol={request.symbol} side={request.side} "
                f"qty={request.qty} error={e}",
                exc_info=True,
            )
            return OrderResponse(
                order_id="",
                status="rejected",
                message=str(e),
            )

        return OrderResponse(
            order_id=str(order.ref) if order else "",
            status="submitted",
        )

    def order_target_percent(
        self,
        symbol: str,
        target_pct: float,
    ) -> OrderResponse:
        """按目标百分比下单（backtrader 便捷方法）。

        backtrader 自动计算当前仓位与目标仓位的差额并下单。
        target_pct 为目标仓位占总资产的比例，0.0=清仓，0.10=10%仓位。

        Args:
            symbol: 证券代码
            target_pct: 目标百分比（0.0 ~ 1.0）

        Returns:
            订单响应
        """
        data = self._symbol_to_data.get(symbol)
        if data is None:
            return OrderResponse(
                order_id="",
                status="rejected",
                message=f"未注册标的数据: {symbol}",
            )

        try:
            order = self._strategy.order_target_percent(data=data, target=target_pct)
        except Exception as e:
            logger.error(
                f"回测目标仓位下单失败: symbol={symbol} target={target_pct} error={e}",
                exc_info=True,
            )
            return OrderResponse(
                order_id="",
                status="rejected",
                message=str(e),
            )

        return OrderResponse(
            order_id=str(order.ref) if order else "",
            status="submitted",
        )

    def cancel_order(self, order_id: str) -> bool:
        """撤销订单。"""
        try:
            # 仅遍历 pending 订单，避免遍历全量历史订单
            for order in self._broker.pending:
                if str(order.ref) == order_id:
                    self._broker.cancel(order)
                    return True
            logger.warning(f"撤销订单未找到: {order_id}")
            return False
        except Exception as e:
            logger.error(f"撤销订单失败: {order_id} error={e}", exc_info=True)
            return False

    def get_position(self, symbol: str) -> BrokerPosition:
        """获取单个标的持仓。"""
        data = self._symbol_to_data.get(symbol)
        if data is None:
            return BrokerPosition(symbol=symbol)

        position = self._broker.getposition(data)
        current_price = float(data.close[0])
        # 价格为 NaN 时（数据缺失），使用持仓均价
        if not math.isfinite(current_price):
            current_price = float(position.price) if position.size != 0 else 0.0
        qty = float(position.size)
        market_value = qty * current_price
        avg_price = float(position.price)

        return BrokerPosition(
            symbol=symbol,
            qty=qty,
            avg_price=avg_price,
            market_value=market_value,
            current_price=current_price,
        )

    def get_positions(self) -> dict[str, BrokerPosition]:
        """获取所有持仓（仅返回有持仓的标的）。"""
        result: dict[str, BrokerPosition] = {}
        for symbol in self._symbol_to_data:
            pos = self.get_position(symbol)
            if pos.qty != 0:
                result[symbol] = pos
        return result

    def get_account(self) -> AccountInfo:
        """获取账户信息。"""
        cash = float(self._broker.getcash())
        total_value = float(self._broker.getvalue())
        return AccountInfo(
            cash=cash,
            total_value=total_value,
            positions_value=total_value - cash,
        )

    @staticmethod
    def _get_limit_exectype() -> Any:
        """获取 backtrader Limit 执行类型（类级缓存）。"""
        if BacktestBrokerAdapter._limit_exectype is None:
            import backtrader as bt
            BacktestBrokerAdapter._limit_exectype = bt.Order.Limit
        return BacktestBrokerAdapter._limit_exectype
