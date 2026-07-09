"""Redis Pub/Sub 事件发布 - 盘内监控事件总线

封装 redis_client.publish，提供类型安全的发布接口。
所有事件通过 Redis Pub/Sub 解耦，FastAPI 内的 WS SPI 监听并转发给前端。
"""

from __future__ import annotations

import logging
from typing import Any

from framework.commons.redis_client import redis_client

logger = logging.getLogger("INTRADAY.PUBLISHER")

# Redis Pub/Sub 频道定义
CHANNEL_MINUTE_BAR_READY = "intraday:minute_bar.ready"  # 分钟线就绪事件
CHANNEL_TICK_ANOMALY = "intraday:tick_anomaly"  # Tick 异动事件
CHANNEL_CONTROL = "intraday.control"  # 控制信号（start/stop）
CHANNEL_STATUS = "intraday.status"  # 监控任务状态变更


def publish_minute_bar_ready(symbol: str, trade_time: str, bar: dict[str, Any]) -> None:
    """发布分钟线就绪事件"""
    redis_client.publish(CHANNEL_MINUTE_BAR_READY, {
        "symbol": symbol,
        "trade_time": trade_time,
        "bar": bar,
    })


def publish_tick_anomaly(symbol: str, anomaly_type: str, detail: dict[str, Any]) -> None:
    """发布 Tick 异动事件"""
    redis_client.publish(CHANNEL_TICK_ANOMALY, {
        "symbol": symbol,
        "anomaly_type": anomaly_type,
        "detail": detail,
    })


def publish_control(action: str, payload: dict[str, Any] | None = None) -> None:
    """发布控制信号（Celery Beat 调用）

    Args:
        action: "start" / "stop"
        payload: 附加数据，如动态股票池快照
    """
    message = {"action": action}
    if payload:
        message.update(payload)
    redis_client.publish(CHANNEL_CONTROL, message)
    logger.info("发布控制信号: action=%s", action)


def publish_status(status: str, detail: dict[str, Any] | None = None) -> None:
    """发布监控任务状态变更

    Args:
        status: "started" / "stopped" / "error" / "reconnecting"
        detail: 状态详情
    """
    message = {"status": status}
    if detail:
        message.update(detail)
    redis_client.publish(CHANNEL_STATUS, message)
    logger.info("监控任务状态变更: status=%s", status)
