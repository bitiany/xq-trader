"""QMT 交易服务 — 封装下单、撤单、订阅接口。

查询接口见 QmtQueryService；共用连接与超时控制见 QmtServiceBase。
"""

from __future__ import annotations

from framework.commons.exceptions import BusinessException
from framework.commons.logger import get_logger
from xqtrader.broker.services.qmt_service_base import QmtServiceBase

logger = get_logger(__name__)


class QmtTrader(QmtServiceBase):
    """QMT 交易服务。

    封装 XtQuantTrader 的下单/撤单/订阅接口，
    通过 QmtConnection 获取交易实例，通过 _call_sync_with_timeout 适配异步框架。

    所有 QMT 调用均强制施加超时控制，防止网络挂起永久阻塞事件循环：
    - 下单/撤单/订阅等关键操作：10s
    超时抛 BusinessException，上层（如 submit_qmt_order）可据此决定重试或拒绝。
    """

    # ── 下单 ──────────────────────────────────────────────

    async def order_stock(
        self,
        stock_code: str,
        order_type: int,
        order_volume: int,
        price_type: int,
        price: float = 0,
        strategy_name: str = "",
        order_remark: str = "",
    ) -> int:
        """同步下单。

        Args:
            stock_code: 证券代码，如 "600000.SH"
            order_type: 委托类型（STOCK_BUY=23 / STOCK_SELL=24）
            order_volume: 委托数量（股票以股为单位）
            price_type: 报价类型（FIX_PRICE=11 / LATEST_PRICE=5 等）
            price: 委托价格（指定价时为具体价格，否则填 0）
            strategy_name: 策略名称
            order_remark: 委托备注

        Returns:
            order_id (>0 成功, -1 失败)
        """
        account = self._get_account()
        self._ensure_connected()
        trader = self._connection.trader

        logger.info(
            "下单: stock=%s type=%s volume=%s price_type=%s price=%.4f strategy=%s | "
            "account_id=%s account_type=%s trader=%s",
            stock_code, order_type, order_volume, price_type, price, strategy_name,
            account.account_id, account.account_type, type(trader).__name__,
        )

        order_id: int = await self._call_sync_with_timeout(
            trader.order_stock,
            (account, stock_code, order_type, order_volume, price_type, price,
             strategy_name, order_remark),
            timeout=self._TRADE_TIMEOUT,
            operation_name="下单",
        )

        logger.info(
            "下单返回: stock=%s order_id=%s type=%s",
            stock_code, order_id, type(order_id).__name__,
        )

        if order_id < 0:
            logger.warning("下单失败: stock=%s order_id=%s", stock_code, order_id)
            raise BusinessException(f"下单失败: stock={stock_code}, order_id={order_id}")

        logger.info("下单成功: stock=%s order_id=%s", stock_code, order_id)
        return int(order_id)

    async def order_stock_async(
        self,
        stock_code: str,
        order_type: int,
        order_volume: int,
        price_type: int,
        price: float = 0,
        strategy_name: str = "",
        order_remark: str = "",
    ) -> int:
        """异步下单，回报通过 QmtCallbackHandler.on_order_stock_async_response 推送。

        参数同 order_stock，返回请求序号 seq。
        """
        account = self._get_account()
        self._ensure_connected()
        trader = self._connection.trader

        logger.info(
            "异步下单: stock=%s type=%s volume=%s price_type=%s price=%.4f",
            stock_code, order_type, order_volume, price_type, price,
        )

        seq: int = await self._call_sync_with_timeout(
            trader.order_stock_async,
            (account, stock_code, order_type, order_volume, price_type, price,
             strategy_name, order_remark),
            timeout=self._TRADE_TIMEOUT,
            operation_name="异步下单",
        )

        if seq < 0:
            logger.warning("异步下单失败: stock=%s seq=%s", stock_code, seq)
            raise BusinessException(f"异步下单失败: stock={stock_code}, seq={seq}")

        logger.info("异步下单已提交: stock=%s seq=%s", stock_code, seq)
        return int(seq)

    # ── 撤单 ──────────────────────────────────────────────

    async def cancel_order(self, order_id: int) -> int:
        """同步撤单。

        Args:
            order_id: 委托编号

        Returns:
            0 成功, -1 失败
        """
        account = self._get_account()
        self._ensure_connected()
        trader = self._connection.trader

        logger.info("撤单: order_id=%s", order_id)

        result: int = await self._call_sync_with_timeout(
            trader.cancel_order_stock,
            (account, order_id),
            timeout=self._TRADE_TIMEOUT,
            operation_name="撤单",
        )

        if result < 0:
            logger.warning("撤单失败: order_id=%s result=%s", order_id, result)
            raise BusinessException(f"撤单失败: order_id={order_id}, result={result}")

        logger.info("撤单成功: order_id=%s", order_id)
        return int(result)

    async def cancel_order_async(self, order_id: int) -> int:
        """异步撤单，回报通过 QmtCallbackHandler.on_cancel_order_stock_async_response 推送。"""
        account = self._get_account()
        self._ensure_connected()
        trader = self._connection.trader

        logger.info("异步撤单: order_id=%s", order_id)

        seq: int = await self._call_sync_with_timeout(
            trader.cancel_order_stock_async,
            (account, order_id),
            timeout=self._TRADE_TIMEOUT,
            operation_name="异步撤单",
        )

        if seq < 0:
            logger.warning("异步撤单失败: order_id=%s seq=%s", order_id, seq)
            raise BusinessException(f"异步撤单失败: order_id={order_id}, seq={seq}")

        logger.info("异步撤单已提交: order_id=%s seq=%s", order_id, seq)
        return int(seq)

    # ── 订阅 ──────────────────────────────────────────────

    async def subscribe_account(self) -> int:
        """订阅账号信息（资金/委托/成交/持仓推送）。

        Returns:
            0 成功，非 0 失败。
        """
        account = self._get_account()
        self._ensure_connected()
        trader = self._connection.trader

        result: int = await self._call_sync_with_timeout(
            trader.subscribe,
            (account,),
            timeout=self._TRADE_TIMEOUT,
            operation_name="订阅账号",
        )

        if result != 0:
            logger.warning("订阅账号失败: account=%s result=%s", account.account_id, result)
            raise BusinessException(
                f"订阅账号失败: account={account.account_id}, result={result}"
            )

        logger.info("订阅账号成功: account=%s result=%s", account.account_id, result)
        return int(result)

    async def unsubscribe_account(self) -> int:
        """反订阅账号信息。

        Returns:
            0 成功，非 0 失败。
        """
        account = self._get_account()
        self._ensure_connected()
        trader = self._connection.trader

        result: int = await self._call_sync_with_timeout(
            trader.unsubscribe,
            (account,),
            timeout=self._TRADE_TIMEOUT,
            operation_name="反订阅账号",
        )

        if result != 0:
            logger.warning("反订阅账号失败: account=%s result=%s", account.account_id, result)
            raise BusinessException(
                f"反订阅账号失败: account={account.account_id}, result={result}"
            )

        logger.info("反订阅账号成功: account=%s result=%s", account.account_id, result)
        return int(result)
