"""QMT 交易回调处理器 — 继承 XtQuantTraderCallback，处理交易事件。"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from xtquant.xttrader import XtQuantTraderCallback

from xqtrader.broker.services.qmt_connection import QmtConnection

logger = logging.getLogger(__name__)

# 自动重连间隔（秒）
_RECONNECT_INTERVAL = 5


class QmtCallbackHandler(XtQuantTraderCallback):
    """QMT 交易回调处理器。

    继承 XtQuantTraderCallback，重写各回调方法，
    记录关键交易事件日志，便于追踪委托/成交/持仓变动。
    断连时自动触发重连。
    """

    def __init__(self, main_loop: asyncio.AbstractEventLoop | None = None) -> None:
        super().__init__()
        self._connection = QmtConnection.get_instance()
        self._reconnect_timer: threading.Timer | None = None
        self._main_loop = main_loop

    def on_connected(self) -> None:
        logger.info("QMT 交易回调: 连接成功")

    def on_disconnected(self) -> None:
        logger.warning("QMT 交易回调: 连接断开，将在 %ds 后自动重连", _RECONNECT_INTERVAL)
        self._connection.mark_disconnected()
        self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        """调度自动重连（在后台线程中延迟执行）。"""
        if self._reconnect_timer is not None:
            self._reconnect_timer.cancel()

        def _do_reconnect() -> None:
            try:
                result = self._connection.reconnect()
                if result == 0:
                    self._connection.trader.register_callback(self)
                    logger.info("QMT 交易自动重连成功")
                    # 重连后重新订阅账号：调度回主事件循环
                    from xqtrader.broker.services.qmt_trader import QmtTrader
                    trader = QmtTrader()
                    if self._main_loop is not None and not self._main_loop.is_closed():
                        asyncio.run_coroutine_threadsafe(trader.subscribe_account(), self._main_loop)
                    else:
                        logger.warning("QMT 重连后主事件循环不可用，跳过订阅账号")
                else:
                    logger.warning("QMT 交易自动重连失败: result=%s，将在 %ds 后重试", result, _RECONNECT_INTERVAL)
                    self._schedule_reconnect()
            except Exception as e:
                logger.error("QMT 交易自动重连异常: %s", e, exc_info=True)
                self._schedule_reconnect()

        self._reconnect_timer = threading.Timer(_RECONNECT_INTERVAL, _do_reconnect)
        self._reconnect_timer.daemon = True
        self._reconnect_timer.start()

    def on_account_status(self, status: Any) -> None:
        logger.info(
            "QMT 交易回调: 账号状态变动 account_id=%s account_type=%s status=%s",
            getattr(status, "account_id", ""),
            getattr(status, "account_type", ""),
            getattr(status, "status", ""),
        )

    def on_stock_asset(self, asset: Any) -> None:
        logger.info(
            "QMT 交易回调: 资金变动 account_id=%s cash=%.2f total_asset=%.2f market_value=%.2f",
            getattr(asset, "account_id", ""),
            getattr(asset, "cash", 0),
            getattr(asset, "total_asset", 0),
            getattr(asset, "market_value", 0),
        )

    def on_stock_order(self, order: Any) -> None:
        logger.info(
            "QMT 交易回调: 委托变动 order_id=%s stock=%s order_type=%s volume=%s traded=%s status=%s msg=%s",
            getattr(order, "order_id", ""),
            getattr(order, "stock_code", ""),
            getattr(order, "order_type", ""),
            getattr(order, "order_volume", ""),
            getattr(order, "traded_volume", ""),
            getattr(order, "order_status", ""),
            getattr(order, "status_msg", ""),
        )

    def on_stock_trade(self, trade: Any) -> None:
        logger.info(
            "QMT 交易回调: 成交回报 stock=%s price=%.4f volume=%s amount=%.2f order_id=%s",
            getattr(trade, "stock_code", ""),
            getattr(trade, "traded_price", 0),
            getattr(trade, "traded_volume", ""),
            getattr(trade, "traded_amount", 0),
            getattr(trade, "order_id", ""),
        )

    def on_stock_position(self, position: Any) -> None:
        logger.info(
            "QMT 交易回调: 持仓变动 stock=%s volume=%s can_use=%s market_value=%.2f",
            getattr(position, "stock_code", ""),
            getattr(position, "volume", ""),
            getattr(position, "can_use_volume", ""),
            getattr(position, "market_value", 0),
        )

    def on_order_error(self, order_error: Any) -> None:
        logger.error(
            "QMT 交易回调: 下单失败 order_id=%s error_id=%s error_msg=%s",
            getattr(order_error, "order_id", ""),
            getattr(order_error, "error_id", ""),
            getattr(order_error, "error_msg", ""),
            exc_info=True,
        )

    def on_cancel_error(self, cancel_error: Any) -> None:
        logger.error(
            "QMT 交易回调: 撤单失败 order_id=%s error_id=%s error_msg=%s",
            getattr(cancel_error, "order_id", ""),
            getattr(cancel_error, "error_id", ""),
            getattr(cancel_error, "error_msg", ""),
            exc_info=True,
        )

    def on_order_stock_async_response(self, response: Any) -> None:
        logger.info(
            "QMT 交易回调: 异步下单回报 order_id=%s seq=%s error_msg=%s",
            getattr(response, "order_id", ""),
            getattr(response, "seq", ""),
            getattr(response, "error_msg", ""),
        )

    def on_cancel_order_stock_async_response(self, response: Any) -> None:
        logger.info(
            "QMT 交易回调: 异步撤单回报 order_id=%s cancel_result=%s error_msg=%s",
            getattr(response, "order_id", ""),
            getattr(response, "cancel_result", ""),
            getattr(response, "error_msg", ""),
        )
