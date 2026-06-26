"""QMT 查询服务 — 封装资金/委托/成交/持仓/账号查询接口。"""

from __future__ import annotations

from typing import Any

from framework.commons.exceptions import BusinessException
from framework.commons.logger import get_logger
from xqtrader.broker.services.qmt_service_base import QmtServiceBase

logger = get_logger(__name__)


class QmtQueryService(QmtServiceBase):
    """QMT 查询服务。

    封装 XtQuantTrader 的查询接口，通过 QmtConnection 获取交易实例，
    通过 _call_sync_with_timeout 适配异步框架并施加超时控制。
    """

    async def query_asset(self) -> dict[str, Any]:
        """查询资金资产。

        Raises:
            BusinessException: 当 QMT 返回 None（账户未连接/查询异常）时抛出，
                由调用方（如 broker/router.query_asset）捕获后返回降级 dict。
        """
        account = self._get_account()
        self._ensure_connected()
        trader = self._connection.trader

        asset = await self._call_sync_with_timeout(
            trader.query_stock_asset,
            (account,),
            timeout=self._QUERY_TIMEOUT,
            operation_name="查询资金",
        )
        if asset is None:
            logger.warning("查询资产为空: account=%s", account.account_id)
            raise BusinessException(f"查询资产为空: account={account.account_id}")

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
        self._ensure_connected()
        trader = self._connection.trader

        orders = await self._call_sync_with_timeout(
            trader.query_stock_orders,
            (account, cancelable_only),
            timeout=self._QUERY_TIMEOUT,
            operation_name="查询委托",
        )
        return [self._order_to_dict(o) for o in (orders or [])]

    async def query_order(self, order_id: int) -> dict[str, Any] | None:
        """查询单笔委托。"""
        account = self._get_account()
        self._ensure_connected()
        trader = self._connection.trader

        order = await self._call_sync_with_timeout(
            trader.query_stock_order,
            (account, order_id),
            timeout=self._QUERY_TIMEOUT,
            operation_name="查询单笔委托",
        )
        return self._order_to_dict(order) if order else None

    async def query_trades(self) -> list[dict[str, Any]]:
        """查询当日成交。"""
        account = self._get_account()
        self._ensure_connected()
        trader = self._connection.trader

        trades = await self._call_sync_with_timeout(
            trader.query_stock_trades,
            (account,),
            timeout=self._QUERY_TIMEOUT,
            operation_name="查询成交",
        )
        return [self._trade_to_dict(t) for t in (trades or [])]

    async def query_positions(self) -> list[dict[str, Any]]:
        """查询所有持仓。"""
        account = self._get_account()
        self._ensure_connected()
        trader = self._connection.trader

        positions = await self._call_sync_with_timeout(
            trader.query_stock_positions,
            (account,),
            timeout=self._QUERY_TIMEOUT,
            operation_name="查询持仓",
        )
        return [self._position_to_dict(p) for p in (positions or [])]

    async def query_position(self, stock_code: str) -> dict[str, Any] | None:
        """查询单只股票持仓。"""
        account = self._get_account()
        self._ensure_connected()
        trader = self._connection.trader

        position = await self._call_sync_with_timeout(
            trader.query_stock_position,
            (account, stock_code),
            timeout=self._QUERY_TIMEOUT,
            operation_name="查询单只持仓",
        )
        return self._position_to_dict(position) if position else None

    async def query_account_infos(self) -> list[dict[str, Any]]:
        """查询所有资金账号。"""
        self._ensure_connected()
        trader = self._connection.trader

        infos = await self._call_sync_with_timeout(
            trader.query_account_infos,
            (),
            timeout=self._QUERY_TIMEOUT,
            operation_name="查询资金账号",
        )
        return [
            {
                "account_id": getattr(i, "account_id", ""),
                "account_type": getattr(i, "account_type", ""),
            }
            for i in (infos or [])
        ]

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
