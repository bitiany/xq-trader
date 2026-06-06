"""QMT 连接管理 — 封装 XtQuantTrader 的连接生命周期。"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING

from framework.config.settings import settings

if TYPE_CHECKING:
    from xtquant.xttrader import XtQuantTrader

logger = logging.getLogger(__name__)


class QmtConnection:
    """QMT 交易连接管理器（单例）。

    管理 XtQuantTrader 实例的创建、连接、断开和重连。
    xtquant 是同步+回调式 API，XtQuantTrader.start() 会启动内部线程，
    因此本类不需要额外维护线程。
    """

    _instance: QmtConnection | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._trader: XtQuantTrader | None = None
        self._connected = False
        self._session_id = 0

    @classmethod
    def get_instance(cls) -> QmtConnection:
        """获取单例实例。"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def is_connected(self) -> bool:
        return self._connected

    def mark_disconnected(self) -> None:
        """标记连接已断开（由回调处理器在 on_disconnected 时调用）。"""
        if self._connected:
            self._connected = False
            self._trader = None
            logger.warning("QMT 交易连接已被标记为断开")

    @property
    def trader(self) -> XtQuantTrader:
        """获取 XtQuantTrader 实例，未连接时抛出异常。"""
        if self._trader is None or not self._connected:
            raise RuntimeError("QMT 交易连接未建立，请先调用 connect()")
        return self._trader

    def connect(self) -> int:
        """连接 MiniQMT 交易服务。

        Returns:
            0 表示成功，非 0 表示失败。
        """
        if self._connected and self._trader is not None:
            logger.warning("QMT 交易连接已建立，跳过重复连接")
            return 0

        from xtquant.xttrader import XtQuantTrader  # noqa: F811

        qmt = settings.QMT
        if not qmt.QMT_USERDATA_PATH:
            raise ValueError("QMT_USERDATA_PATH 未配置，无法连接交易服务")

        self._session_id += 1
        self._trader = XtQuantTrader(qmt.QMT_USERDATA_PATH, self._session_id)
        self._trader.start()

        result = self._trader.connect()
        if result == 0:
            self._connected = True
            logger.info(
                "QMT 交易连接成功: path=%s session_id=%s",
                qmt.QMT_USERDATA_PATH, self._session_id,
            )
        else:
            self._trader = None
            logger.error("QMT 交易连接失败: result=%s path=%s", result, qmt.QMT_USERDATA_PATH)

        return int(result)

    def disconnect(self) -> None:
        """断开 QMT 交易连接。"""
        if self._trader is not None:
            self._trader.stop()
            logger.info("QMT 交易连接已断开")
        self._trader = None
        self._connected = False

    def reconnect(self) -> int:
        """重新连接 QMT 交易服务。"""
        logger.info("QMT 交易重连中...")
        self.disconnect()
        return self.connect()

    async def connect_async(self) -> int:
        """异步连接 MiniQMT 交易服务。"""
        return await asyncio.to_thread(self.connect)

    async def disconnect_async(self) -> None:
        """异步断开 QMT 交易连接。"""
        await asyncio.to_thread(self.disconnect)

    async def reconnect_async(self) -> int:
        """异步重新连接 QMT 交易服务。"""
        return await asyncio.to_thread(self.reconnect)
