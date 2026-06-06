"""QMT 交易服务 — 封装下单、撤单、查询等交易接口。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from xtquant.xttype import StockAccount

from framework.commons.exceptions import BusinessException
from framework.config.settings import settings
from xqtrader.domain.broker.services.qmt_connection import QmtConnection

logger = logging.getLogger(__name__)


class QmtTrader:
    """QMT 交易服务。

    封装 XtQuantTrader 的下单/撤单/查询接口，
    通过 QmtConnection 获取交易实例，通过 asyncio.to_thread 适配异步框架。
    """

    def __init__(self) -> None:
        self._connection = QmtConnection.get_instance()

    def _get_account(self) -> StockAccount:
        """获取当前配置的交易账号。"""
        qmt = settings.QMT
        if not qmt.QMT_ACCOUNT_ID:
            raise BusinessException("QMT_ACCOUNT_ID 未配置")
        return StockAccount(qmt.QMT_ACCOUNT_ID, qmt.QMT_ACCOUNT_TYPE)

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
        trader = self._connection.trader

        logger.info(
            "下单: stock=%s type=%s volume=%s price_type=%s price=%.4f strategy=%s",
            stock_code, order_type, order_volume, price_type, price, strategy_name,
        )

        order_id: int = await asyncio.to_thread(
            trader.order_stock,
            account, stock_code, order_type, order_volume, price_type, price,
            strategy_name, order_remark,
        )

        if order_id < 0:
            logger.error("下单失败: stock=%s order_id=%s", stock_code, order_id)
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
        trader = self._connection.trader

        logger.info(
            "异步下单: stock=%s type=%s volume=%s price_type=%s price=%.4f",
            stock_code, order_type, order_volume, price_type, price,
        )

        seq: int = await asyncio.to_thread(
            trader.order_stock_async,
            account, stock_code, order_type, order_volume, price_type, price,
            strategy_name, order_remark,
        )

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
        trader = self._connection.trader

        logger.info("撤单: order_id=%s", order_id)

        result: int = await asyncio.to_thread(
            trader.cancel_order_stock, account, order_id,
        )

        if result < 0:
            logger.error("撤单失败: order_id=%s result=%s", order_id, result)
            raise BusinessException(f"撤单失败: order_id={order_id}, result={result}")

        logger.info("撤单成功: order_id=%s", order_id)
        return int(result)

    async def cancel_order_async(self, order_id: int) -> int:
        """异步撤单，回报通过 QmtCallbackHandler.on_cancel_order_stock_async_response 推送。"""
        account = self._get_account()
        trader = self._connection.trader

        logger.info("异步撤单: order_id=%s", order_id)

        seq: int = await asyncio.to_thread(
            trader.cancel_order_stock_async, account, order_id,
        )

        logger.info("异步撤单已提交: order_id=%s seq=%s", order_id, seq)
        return int(seq)

    # ── 查询 ──────────────────────────────────────────────

    async def query_asset(self) -> dict[str, Any]:
        """查询资金资产。"""
        account = self._get_account()
        trader = self._connection.trader

        asset = await asyncio.to_thread(trader.query_stock_asset, account)
        if asset is None:
            logger.warning("查询资产为空: account=%s", account.account_id)
            return {}

        return {
            "account_id": asset.account_id,
            "cash": asset.cash,
            "frozen_cash": asset.frozen_cash,
            "market_value": asset.market_value,
            "total_asset": asset.total_asset,
            "fetch_balance": asset.fetch_balance,
        }

    async def query_orders(self, cancelable_only: bool = False) -> list[dict[str, Any]]:
        """查询当日委托。

        Args:
            cancelable_only: 是否仅查询可撤委托
        """
        account = self._get_account()
        trader = self._connection.trader

        orders = await asyncio.to_thread(trader.query_stock_orders, account, cancelable_only)
        return [self._order_to_dict(o) for o in (orders or [])]

    async def query_order(self, order_id: int) -> dict[str, Any] | None:
        """查询单笔委托。"""
        account = self._get_account()
        trader = self._connection.trader

        order = await asyncio.to_thread(trader.query_stock_order, account, order_id)
        return self._order_to_dict(order) if order else None

    async def query_trades(self) -> list[dict[str, Any]]:
        """查询当日成交。"""
        account = self._get_account()
        trader = self._connection.trader

        trades = await asyncio.to_thread(trader.query_stock_trades, account)
        return [self._trade_to_dict(t) for t in (trades or [])]

    async def query_positions(self) -> list[dict[str, Any]]:
        """查询所有持仓。"""
        account = self._get_account()
        trader = self._connection.trader

        positions = await asyncio.to_thread(trader.query_stock_positions, account)
        return [self._position_to_dict(p) for p in (positions or [])]

    async def query_position(self, stock_code: str) -> dict[str, Any] | None:
        """查询单只股票持仓。"""
        account = self._get_account()
        trader = self._connection.trader

        position = await asyncio.to_thread(trader.query_stock_position, account, stock_code)
        return self._position_to_dict(position) if position else None

    async def query_account_infos(self) -> list[dict[str, Any]]:
        """查询所有资金账号。"""
        trader = self._connection.trader

        infos = await asyncio.to_thread(trader.query_account_infos)
        return [
            {
                "account_id": getattr(i, "account_id", ""),
                "account_type": getattr(i, "account_type", ""),
            }
            for i in (infos or [])
        ]

    # ── 订阅 ──────────────────────────────────────────────

    async def subscribe_account(self) -> int:
        """订阅账号信息（资金/委托/成交/持仓推送）。"""
        account = self._get_account()
        trader = self._connection.trader

        result: int = await asyncio.to_thread(trader.subscribe, account)
        logger.info("订阅账号: account=%s result=%s", account.account_id, result)
        return int(result)

    async def unsubscribe_account(self) -> int:
        """反订阅账号信息。"""
        account = self._get_account()
        trader = self._connection.trader

        result: int = await asyncio.to_thread(trader.unsubscribe, account)
        logger.info("反订阅账号: account=%s result=%s", account.account_id, result)
        return int(result)

    # ── 数据转换 ──────────────────────────────────────────

    @staticmethod
    def _order_to_dict(order: Any) -> dict[str, Any]:
        return {
            "account_id": order.account_id,
            "stock_code": order.stock_code,
            "order_id": order.order_id,
            "order_sysid": order.order_sysid,
            "order_time": order.order_time,
            "order_type": order.order_type,
            "order_volume": order.order_volume,
            "price_type": order.price_type,
            "price": order.price,
            "traded_volume": order.traded_volume,
            "traded_price": order.traded_price,
            "order_status": order.order_status,
            "status_msg": order.status_msg,
            "strategy_name": order.strategy_name,
            "order_remark": order.order_remark,
        }

    @staticmethod
    def _trade_to_dict(trade: Any) -> dict[str, Any]:
        return {
            "account_id": trade.account_id,
            "stock_code": trade.stock_code,
            "order_type": trade.order_type,
            "traded_id": trade.traded_id,
            "traded_time": trade.traded_time,
            "traded_price": trade.traded_price,
            "traded_volume": trade.traded_volume,
            "traded_amount": trade.traded_amount,
            "order_id": trade.order_id,
            "order_sysid": trade.order_sysid,
        }

    @staticmethod
    def _position_to_dict(position: Any) -> dict[str, Any]:
        return {
            "account_id": position.account_id,
            "stock_code": position.stock_code,
            "volume": position.volume,
            "can_use_volume": position.can_use_volume,
            "open_price": position.open_price,
            "market_value": position.market_value,
            "frozen_volume": position.frozen_volume,
            "on_road_volume": position.on_road_volume,
            "yesterday_volume": position.yesterday_volume,
            "avg_price": position.avg_price,
            "direction": position.direction,
        }
