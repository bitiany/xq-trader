"""QMT 交易回调处理器 — 继承 XtQuantTraderCallback，处理交易事件。

将 QMT 的同步回调通过 asyncio.run_coroutine_threadsafe 调度到主事件循环，
由 QmtOrderProcessor 转换为 OMS 状态变更（订单/成交/资金/持仓）。
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from xtquant.xttrader import XtQuantTraderCallback

from framework.commons.logger import get_logger
from xqtrader.broker.services.qmt_connection import QmtConnection
from xqtrader.broker.services.qmt_order_processor import QmtOrderProcessor
from xqtrader.broker.services.qmt_trader import QmtTrader

logger = get_logger(__name__)

# 重连初始间隔（秒），失败后指数退避至上限
_RECONNECT_INTERVAL = 5
_RECONNECT_MAX_INTERVAL = 300


class QmtCallbackHandler(XtQuantTraderCallback):
    """QMT 交易回调处理器。

    继承 XtQuantTraderCallback，重写各回调方法：
    - 将 QMT 回调对象转为 dict，调度到主事件循环交由 QmtOrderProcessor 处理
    - 记录关键交易事件日志，便于追踪委托/成交/持仓变动
    - 断连时通过指数退避自动重连
    """

    _instance: QmtCallbackHandler | None = None
    _instance_lock = threading.Lock()

    def __init__(self, main_loop: asyncio.AbstractEventLoop | None = None) -> None:
        super().__init__()
        self._connection = QmtConnection.get_instance()
        self._reconnect_timer: threading.Timer | None = None
        self._reconnect_attempt = 0
        self._main_loop = main_loop
        self._processor = QmtOrderProcessor()

    @classmethod
    def get_instance(cls, main_loop: asyncio.AbstractEventLoop | None = None) -> QmtCallbackHandler:
        """获取单例实例；首次调用时若提供 main_loop 则绑定。"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls(main_loop=main_loop)
                    return cls._instance
        # 后续调用若传入新 main_loop，则更新绑定
        if main_loop is not None and cls._instance._main_loop is not main_loop:
            cls._instance._main_loop = main_loop
        return cls._instance

    # ── 连接事件 ──────────────────────────────────────────

    def on_connected(self) -> None:
        logger.info("QMT 交易回调: 连接成功")
        self._reconnect_attempt = 0

    def on_disconnected(self) -> None:
        logger.warning("QMT 交易回调: 连接断开，将自动重连")
        self._connection.mark_disconnected()
        self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        """调度自动重连（指数退避，避免断网时日志刷屏）。"""
        if self._reconnect_timer is not None:
            self._reconnect_timer.cancel()

        self._reconnect_attempt += 1
        # 指数退避：interval * 2^(attempt-1)，封顶到 _RECONNECT_MAX_INTERVAL
        delay = min(
            _RECONNECT_INTERVAL * (2 ** (self._reconnect_attempt - 1)),
            _RECONNECT_MAX_INTERVAL,
        )
        logger.info("QMT 第 %s 次重连将在 %ss 后执行", self._reconnect_attempt, delay)

        def _do_reconnect() -> None:
            try:
                result = self._connection.reconnect()
                if result == 0:
                    self._connection.trader.register_callback(self)
                    logger.info("QMT 交易自动重连成功")
                    self._reconnect_attempt = 0
                    if self._main_loop is not None and not self._main_loop.is_closed():
                        asyncio.run_coroutine_threadsafe(
                            self._resubscribe_after_reconnect(), self._main_loop,
                        )
                    else:
                        logger.warning("QMT 重连后主事件循环不可用，跳过订阅账号")
                else:
                    logger.warning("QMT 交易自动重连失败: result=%s", result)
                    self._schedule_reconnect()
            except Exception:
                logger.error("QMT 交易自动重连异常", exc_info=True)
                self._schedule_reconnect()

        self._reconnect_timer = threading.Timer(delay, _do_reconnect)
        self._reconnect_timer.daemon = True
        self._reconnect_timer.start()

    async def _resubscribe_after_reconnect(self) -> None:
        """重连后重新订阅账号。"""
        try:
            trader = QmtTrader()
            await trader.subscribe_account()
        except Exception:
            logger.error("QMT 重连后订阅账号失败", exc_info=True)

    # ── 业务回调 ──────────────────────────────────────────

    def on_account_status(self, status: Any) -> None:
        logger.info(
            "QMT 交易回调: 账号状态变动 account_id=%s account_type=%s status=%s",
            getattr(status, "account_id", ""),
            getattr(status, "account_type", ""),
            getattr(status, "status", ""),
        )

    def on_stock_asset(self, asset: Any) -> None:
        asset_dict = {
            "account_id": getattr(asset, "account_id", ""),
            "cash": getattr(asset, "cash", 0),
            "frozen_cash": getattr(asset, "frozen_cash", 0),
            "market_value": getattr(asset, "market_value", 0),
            "total_asset": getattr(asset, "total_asset", 0),
        }
        logger.info(
            "QMT 交易回调: 资金变动 account_id=%s cash=%.2f total_asset=%.2f market_value=%.2f",
            asset_dict["account_id"], asset_dict["cash"],
            asset_dict["total_asset"], asset_dict["market_value"],
        )
        self._dispatch(
            self._processor.process_asset_callback(asset_dict),
            callback_type="asset",
            callback_data=asset_dict,
        )

    def on_stock_order(self, order: Any) -> None:
        order_dict = {
            "account_id": getattr(order, "account_id", ""),
            "order_id": getattr(order, "order_id", ""),
            "stock_code": getattr(order, "stock_code", ""),
            "order_type": getattr(order, "order_type", 0),
            "order_volume": getattr(order, "order_volume", 0),
            "traded_volume": getattr(order, "traded_volume", 0),
            "traded_price": getattr(order, "traded_price", 0),
            "order_status": getattr(order, "order_status", 255),
            "status_msg": getattr(order, "status_msg", ""),
        }
        logger.info(
            "QMT 交易回调: 委托变动 order_id=%s stock=%s order_type=%s volume=%s traded=%s status=%s msg=%s",
            order_dict["order_id"], order_dict["stock_code"],
            order_dict["order_type"], order_dict["order_volume"],
            order_dict["traded_volume"], order_dict["order_status"],
            order_dict["status_msg"],
        )
        self._dispatch(
            self._processor.process_order_callback(order_dict),
            callback_type="order",
            callback_data=order_dict,
        )

    def on_stock_trade(self, trade: Any) -> None:
        trade_dict = {
            "account_id": getattr(trade, "account_id", ""),
            "stock_code": getattr(trade, "stock_code", ""),
            "order_id": getattr(trade, "order_id", ""),
            "traded_id": getattr(trade, "traded_id", ""),
            "traded_price": getattr(trade, "traded_price", 0),
            "traded_volume": getattr(trade, "traded_volume", 0),
            "traded_amount": getattr(trade, "traded_amount", 0),
        }
        logger.info(
            "QMT 交易回调: 成交回报 stock=%s price=%.4f volume=%s amount=%.2f order_id=%s",
            trade_dict["stock_code"], trade_dict["traded_price"],
            trade_dict["traded_volume"], trade_dict["traded_amount"],
            trade_dict["order_id"],
        )
        self._dispatch(
            self._processor.process_trade_callback(trade_dict),
            callback_type="trade",
            callback_data=trade_dict,
        )

    def on_stock_position(self, position: Any) -> None:
        position_dict = {
            "account_id": getattr(position, "account_id", ""),
            "stock_code": getattr(position, "stock_code", ""),
            "volume": getattr(position, "volume", 0),
            "can_use_volume": getattr(position, "can_use_volume", 0),
            "market_value": getattr(position, "market_value", 0),
        }
        logger.info(
            "QMT 交易回调: 持仓变动 stock=%s volume=%s can_use=%s market_value=%.2f",
            position_dict["stock_code"], position_dict["volume"],
            position_dict["can_use_volume"], position_dict["market_value"],
        )
        self._dispatch(
            self._processor.process_position_callback(position_dict),
            callback_type="position",
            callback_data=position_dict,
        )

    # ── 错误回调 ──────────────────────────────────────────

    def on_order_error(self, order_error: Any) -> None:
        # QMT 下单失败非异常路径，使用 warning 而非 error+exc_info
        logger.warning(
            "QMT 交易回调: 下单失败 order_id=%s error_id=%s error_msg=%s",
            getattr(order_error, "order_id", ""),
            getattr(order_error, "error_id", ""),
            getattr(order_error, "error_msg", ""),
        )

    def on_cancel_error(self, cancel_error: Any) -> None:
        logger.warning(
            "QMT 交易回调: 撤单失败 order_id=%s error_id=%s error_msg=%s",
            getattr(cancel_error, "order_id", ""),
            getattr(cancel_error, "error_id", ""),
            getattr(cancel_error, "error_msg", ""),
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

    # ── 内部工具 ──────────────────────────────────────────

    def _dispatch(
        self,
        coro: Any,
        *,
        callback_type: str,
        callback_data: dict[str, Any],
    ) -> None:
        """将协程调度到主事件循环；若循环不可用则取消协程并告警。

        失败时保留原始回调负载（callback_type + callback_data）写入 error 日志，
        便于事后追溯与人工重放。QMT 回调是单向推送，无重投递机制，原始负载丢失
        即等同成交/委托数据永久丢失。
        """
        if self._main_loop is None or self._main_loop.is_closed():
            logger.warning(
                "主事件循环不可用，丢弃 QMT 回调: type=%s data=%s",
                callback_type, callback_data,
            )
            try:
                coro.close()
            except Exception:
                logger.warning("关闭未调度协程失败", exc_info=True)
            return
        future = asyncio.run_coroutine_threadsafe(coro, self._main_loop)

        def _log_failure(fut: Any) -> None:
            try:
                fut.result()
            except Exception:
                logger.error(
                    "QMT 回调处理失败，原始负载已保留供人工对账: "
                    "type=%s data=%s",
                    callback_type, callback_data,
                    exc_info=True,
                )

        future.add_done_callback(_log_failure)
