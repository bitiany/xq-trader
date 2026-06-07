"""Broker连接状态SPI"""

from __future__ import annotations

import time

from xtquant import xtdata

from framework.commons.logger import get_logger
from framework.ws.exceptions import WsSpiError
from xqtrader.broker.services.qmt_connection import QmtConnection
from xqtrader.ws.constants import WsTopic

from .. import TopicSpi, register_spi

logger = get_logger("ws.spi.broker_status")


@register_spi
class BrokerStatusSpi(TopicSpi):
    """Broker连接状态SPI"""

    @property
    def topic_name(self) -> str:
        return WsTopic.BROKER_STATUS

    def execute(self) -> dict:
        market_status = "disconnected"
        trading_status = "disconnected"

        # 检查QMT行情连接
        try:
            result = xtdata.get_trading_dates("SH", count=1)
            if result:
                market_status = "connected"
        except WsSpiError:
            raise
        except Exception as e:
            raise WsSpiError("QMT market check failed") from e

        # 检查QMT交易连接
        try:
            conn = QmtConnection.get_instance()
            if conn.is_connected:
                trading_status = "connected"
        except WsSpiError:
            raise
        except Exception as e:
            raise WsSpiError("QMT trading check failed") from e

        return {
            "market_status": market_status,
            "trading_status": trading_status,
            "timestamp": time.time(),
        }
