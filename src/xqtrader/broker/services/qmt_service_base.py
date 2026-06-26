"""QMT 服务基类 — 封装 QmtTrader / QmtQueryService 共用的连接与超时控制。"""

from __future__ import annotations

import asyncio
from typing import Any

from xtquant.xttype import StockAccount

from framework.commons.exceptions import BusinessException
from framework.commons.logger import get_logger
from framework.config.settings import settings
from xqtrader.broker.services.qmt_connection import QmtConnection

logger = get_logger(__name__)


class QmtServiceBase:
    """QMT 服务基类。

    提供 QmtTrader（下单/撤单/订阅）与 QmtQueryService（查询）共用的：
    - 连接获取（QmtConnection 单例）
    - 连接状态校验（_ensure_connected）
    - 账号构造（_get_account）
    - 同步调用 + 超时控制（_call_sync_with_timeout）

    所有 QMT 调用均强制施加超时控制，防止网络挂起永久阻塞事件循环：
    - 下单/撤单/订阅等关键操作：10s
    - 查询类操作：5s
    超时抛 BusinessException，上层（如 submit_qmt_order）可据此决定重试或拒绝。
    """

    # 下单/撤单/订阅超时（秒）：实盘关键操作
    _TRADE_TIMEOUT: float = 10.0
    # 查询类操作超时（秒）：query_orders/query_asset 等
    _QUERY_TIMEOUT: float = 5.0

    def __init__(self) -> None:
        self._connection = QmtConnection.get_instance()

    def _ensure_connected(self) -> None:
        """确保交易连接已建立，未连接时抛出业务异常。"""
        if not self._connection.is_connected:
            raise BusinessException("QMT 交易连接未建立，请先调用 /broker/connect")

    def _get_account(self) -> StockAccount:
        """获取当前配置的交易账号。"""
        qmt = settings.QMT
        if not qmt.QMT_ACCOUNT_ID:
            raise BusinessException("QMT_ACCOUNT_ID 未配置")
        return StockAccount(qmt.QMT_ACCOUNT_ID, qmt.QMT_ACCOUNT_TYPE)

    @staticmethod
    async def _call_sync_with_timeout(
        func: Any,
        args: tuple[Any, ...],
        *,
        timeout: float,
        operation_name: str,
    ) -> Any:
        """以 asyncio.to_thread + wait_for 执行同步 broker 调用。

        超时抛 BusinessException（提示上层该调用可能瞬时失败，可重试或对账）。
        业务错误由调用方自行判断返回值并抛出。
        """
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(func, *args),
                timeout=timeout,
            )
        except asyncio.TimeoutError as e:
            raise BusinessException(
                f"QMT {operation_name} 超时 ({timeout}s)"
            ) from e
