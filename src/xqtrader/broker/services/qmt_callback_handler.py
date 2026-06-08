"""QMT 交易回调处理器 — 继承 XtQuantTraderCallback，处理交易事件。"""

from __future__ import annotations

import logging
from typing import Any

from xtquant.xttrader import XtQuantTraderCallback

from xqtrader.broker.services.qmt_connection import QmtConnection

logger = logging.getLogger(__name__)


class QmtCallbackHandler(XtQuantTraderCallback):
    """QMT 交易回调处理器。

    继承 XtQuantTraderCallback，重写各回调方法，
    记录关键交易事件日志，便于追踪委托/成交/持仓变动。
    """

    def __init__(self) -> None:
        super().__init__()
        self._connection = QmtConnection.get_instance()

    def on_connected(self) -> None:
        logger.info("QMT 交易回调: 连接成功")

    def on_disconnected(self) -> None:
        logger.warning("QMT 交易回调: 连接断开")
        self._connection.mark_disconnected()

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
