"""账户资产 SPI — 按 broker_type 区分资金来源

- broker_type == "qmt": 实盘，直接查询 QMT 资金
- 其它类型: 从 Redis 缓存读取 td_account 表数据（由 REST API 同步）
"""

from __future__ import annotations

import json
import time
from datetime import date

from xtquant.xttype import StockAccount

from framework.commons.logger import get_logger
from framework.commons.redis_client import redis_client
from framework.config.settings import settings
from framework.ws.exceptions import WsSpiError
from xqtrader.broker.services.qmt_connection import QmtConnection
from xqtrader.domain.trading.enums import BrokerType
from xqtrader.ws.constants import WsTopic

from .. import TopicSpi, register_spi

logger = get_logger("ws.spi.pnl")

# Redis Key 前缀
# 账户资产缓存：trading:account:{account_id}:asset -> JSON
_ACCOUNT_ASSET_PREFIX = "trading:account"
# 当日基准总资产：trading:account:{account_id}:baseline:{YYYY-MM-DD} -> total_asset (str)
_BASELINE_TTL_SECONDS = 3 * 24 * 3600


async def sync_account_assets_to_redis() -> None:
    """将所有账户的元数据同步到 Redis 缓存，供 PnlSpi 读取。

    QMT 账户：缓存 account_id + broker_type，资产由 PnlSpi 实时查询 QMT。
    非 QMT 账户：缓存完整资产数据（从 td_account 表读取）。
    """
    from xqtrader.domain.trading.models.account import TradingAccount

    accounts = await TradingAccount.filter(is_enabled=True)
    for account in accounts:
        key = f"{_ACCOUNT_ASSET_PREFIX}:{account.id}:asset"
        if account.broker_type == BrokerType.QMT:
            # QMT 账户只缓存元数据，资产由 SPI 实时查询
            data = {
                "account_id": account.id,
                "broker_type": account.broker_type,
                "account_code": account.account_code,
            }
        else:
            data = {
                "account_id": account.id,
                "broker_type": account.broker_type,
                "cash": float(account.available_cash),
                "frozen_cash": float(account.frozen_cash),
                "market_value": 0.0,
                "total_asset": float(account.available_cash) + float(account.frozen_cash),
                "today_pnl": 0.0,
                "today_pnl_pct": 0.0,
            }
        redis_client.set(key, json.dumps(data), ex=300)  # 5 分钟过期


@register_spi
class PnlSpi(TopicSpi):
    """P&L SPI — 按账户推送资产数据

    - QMT 账户：直接查询 QMT 获取实时资产
    - 其它账户：从 Redis 缓存读取 td_account 表数据
    """

    @property
    def topic_name(self) -> str:
        return WsTopic.TRADING_PNL

    def execute(self) -> dict:
        try:
            items = []

            # 1. QMT 账户：查询 QMT 实时资产
            qmt_data = self._query_qmt_asset()
            if qmt_data:
                items.append(qmt_data)

            # 2. 一次 SCAN 加载所有账户缓存，按 broker_type 分类
            qmt_account_id, non_qmt_items = self._load_account_assets_from_redis()
            items.extend(non_qmt_items)

            # 如果 QMT 实时查询成功但缺少 account_id，从缓存补充
            if qmt_data and qmt_data.get("account_id") is None and qmt_account_id is not None:
                qmt_data["account_id"] = qmt_account_id

            if not items:
                return self._empty_result("no_accounts")

            return {
                "items": items,
                "timestamp": time.time(),
            }
        except WsSpiError:
            raise
        except Exception as e:
            raise WsSpiError("PnL query failed") from e

    @staticmethod
    def _query_qmt_asset() -> dict | None:
        """查询 QMT 实盘账户资产"""
        conn = QmtConnection.get_instance()
        if not conn.is_connected:
            return None

        qmt = settings.QMT
        if not qmt.QMT_ACCOUNT_ID:
            return None

        account = StockAccount(qmt.QMT_ACCOUNT_ID, qmt.QMT_ACCOUNT_TYPE)
        trader = conn.trader

        asset = trader.query_stock_asset(account)
        if asset is None:
            return None

        total_asset = round(asset.total_asset, 2)
        today_pnl, today_pnl_pct = PnlSpi._calc_today_pnl(qmt.QMT_ACCOUNT_ID, total_asset)

        return {
            "account_id": None,  # 由 execute() 从 Redis 缓存补充
            "broker_type": BrokerType.QMT,
            "cash": round(asset.cash, 2),
            "frozen_cash": round(asset.frozen_cash, 2),
            "market_value": round(asset.market_value, 2),
            "total_asset": total_asset,
            "today_pnl": round(today_pnl, 2),
            "today_pnl_pct": round(today_pnl_pct, 6),
        }

    @staticmethod
    def _load_account_assets_from_redis() -> tuple[int | None, list[dict]]:
        """一次 SCAN 加载所有账户缓存，返回 (qmt_account_id, non_qmt_items)"""
        qmt_account_id: int | None = None
        non_qmt_items: list[dict] = []
        cursor = 0
        while True:
            cursor, keys = redis_client.scan(cursor, match=f"{_ACCOUNT_ASSET_PREFIX}:*:asset", count=100)
            for key in keys:
                if isinstance(key, bytes):
                    key = key.decode()
                raw = redis_client.get(key)
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                    if data.get("broker_type") == BrokerType.QMT:
                        aid = data.get("account_id")
                        qmt_account_id = int(aid) if aid is not None else None
                    else:
                        non_qmt_items.append(data)
                except (json.JSONDecodeError, TypeError):
                    continue
            if cursor == 0:
                break
        return qmt_account_id, non_qmt_items

    @staticmethod
    def _baseline_key(account_id: str) -> str:
        today_str = date.today().isoformat()
        return f"{_ACCOUNT_ASSET_PREFIX}:{account_id}:baseline:{today_str}"

    @classmethod
    def _calc_today_pnl(cls, account_id: str, total_asset: float) -> tuple[float, float]:
        """计算当日盈亏：基准存 Redis，跨重启保持。"""
        key = cls._baseline_key(account_id)

        baseline_str = redis_client.get(key)
        if baseline_str is None:
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
            "items": [],
            "reason": reason,
            "timestamp": time.time(),
        }
