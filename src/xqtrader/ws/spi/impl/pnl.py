"""账户资产SPI"""

from __future__ import annotations

import time
from datetime import date

from xtquant.xttype import StockAccount

from framework.commons.logger import get_logger
from framework.commons.redis_client import redis_client
from framework.config.settings import settings
from framework.ws.exceptions import WsSpiError
from xqtrader.broker.services.qmt_connection import QmtConnection
from xqtrader.ws.constants import WsTopic

from .. import TopicSpi, register_spi

logger = get_logger("ws.spi.pnl")

# Redis Key 前缀：当日基准总资产
# 格式：trading:account:{account_id}:baseline:{YYYY-MM-DD} -> total_asset (str)
# TTL：3 天，覆盖跨节假日场景（后续由定时任务在收盘后写入"昨日收盘总资产"）
_BASELINE_KEY_PREFIX = "trading:account"
_BASELINE_TTL_SECONDS = 3 * 24 * 3600


@register_spi
class PnlSpi(TopicSpi):
    """P&L SPI — 查询QMT真实账户资产，含当日盈亏

    当日盈亏基准持久化到 Redis：
    - 当日首次查询时写入基准（仅当 Redis 中尚无该日基准时）
    - 服务重启后从 Redis 读取，跨重启保持
    - 后续可由定时任务在收盘后写入次日基准（昨日收盘总资产）
    """

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

            total_asset = round(asset.total_asset, 2)
            today_pnl, today_pnl_pct = self._calc_today_pnl(qmt.QMT_ACCOUNT_ID, total_asset)

            return {
                "cash": round(asset.cash, 2),
                "frozen_cash": round(asset.frozen_cash, 2),
                "market_value": round(asset.market_value, 2),
                "total_asset": total_asset,
                "today_pnl": round(today_pnl, 2),
                "today_pnl_pct": round(today_pnl_pct, 6),
                "timestamp": time.time(),
            }
        except WsSpiError:
            raise
        except Exception as e:
            raise WsSpiError("PnL query failed") from e

    @staticmethod
    def _baseline_key(account_id: str) -> str:
        today_str = date.today().isoformat()
        return f"{_BASELINE_KEY_PREFIX}:{account_id}:baseline:{today_str}"

    @classmethod
    def _calc_today_pnl(cls, account_id: str, total_asset: float) -> tuple[float, float]:
        """计算当日盈亏：基准存 Redis，跨重启保持。

        基准来源优先级：
        1. Redis 中已有当日基准 -> 直接使用
        2. Redis 中无 -> 用当前 total_asset 作为基准并写入（首次查询）
        """
        key = cls._baseline_key(account_id)

        baseline_str = redis_client.get(key)
        if baseline_str is None:
            # 首次写入：当前总资产即为基准（pct=0）
            redis_client.set(key, str(total_asset), ex=_BASELINE_TTL_SECONDS)
            logger.info("当日基准资产已写入 Redis: account=%s baseline=%s key=%s", account_id, total_asset, key)
            return 0.0, 0.0

        try:
            baseline = float(baseline_str)
        except (TypeError, ValueError):
            logger.warning("Redis 基准值格式异常，重置: key=%s value=%r", key, baseline_str)
            redis_client.set(key, str(total_asset), ex=_BASELINE_TTL_SECONDS)
            return 0.0, 0.0

        if baseline <= 0:
            return 0.0, 0.0

        pnl = total_asset - baseline
        pct = pnl / baseline
        return pnl, pct

    @staticmethod
    def _empty_result(reason: str) -> dict:
        return {
            "cash": 0.0,
            "frozen_cash": 0.0,
            "market_value": 0.0,
            "total_asset": 0.0,
            "today_pnl": 0.0,
            "today_pnl_pct": 0.0,
            "reason": reason,
            "timestamp": time.time(),
        }
