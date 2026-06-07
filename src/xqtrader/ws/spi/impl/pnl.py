"""账户资产SPI"""

from __future__ import annotations

import time

from xtquant.xttype import StockAccount

from framework.commons.logger import get_logger
from framework.config.settings import settings
from framework.ws.exceptions import WsSpiError
from xqtrader.broker.services.qmt_connection import QmtConnection
from xqtrader.ws.constants import WsTopic

from .. import TopicSpi, register_spi

logger = get_logger("ws.spi.pnl")


@register_spi
class PnlSpi(TopicSpi):
    """P&L SPI — 查询QMT真实账户资产"""

    @property
    def topic_name(self) -> str:
        return WsTopic.TRADING_PNL

    def execute(self) -> dict:
        try:
            conn = QmtConnection.get_instance()
            if not conn.is_connected:
                return self._empty_result("trading_disconnected")

            qmt = settings.QMT
            if not qmt.QMT_ACCOUNT_ID:
                return self._empty_result("account_not_configured")

            account = StockAccount(qmt.QMT_ACCOUNT_ID, qmt.QMT_ACCOUNT_TYPE)
            trader = conn.trader

            asset = trader.query_stock_asset(account)
            if asset is None:
                return self._empty_result("asset_query_empty")

            return {
                "cash": round(asset.cash, 2),
                "frozen_cash": round(asset.frozen_cash, 2),
                "market_value": round(asset.market_value, 2),
                "total_asset": round(asset.total_asset, 2),
                "timestamp": time.time(),
            }
        except WsSpiError:
            raise
        except Exception as e:
            raise WsSpiError("PnL query failed") from e

    @staticmethod
    def _empty_result(reason: str) -> dict:
        return {
            "cash": 0.0,
            "frozen_cash": 0.0,
            "market_value": 0.0,
            "total_asset": 0.0,
            "reason": reason,
            "timestamp": time.time(),
        }
