"""Redis Pub/Sub 事件发布 - 盘内监控事件总线

封装 redis_client.publish，提供类型安全的发布接口。
盘内事件同时发布到两个频道：
1. intraday:* - 内部事件总线（服务间解耦）
2. ws:topic:ws.intraday.* - WebSocket 推送频道（前端实时接收）
"""

from __future__ import annotations

import logging
from typing import Any

from framework.commons.redis_client import redis_client
from framework.ws.messages import CHANNEL_PREFIX

logger = logging.getLogger("INTRADAY.PUBLISHER")

# Redis Pub/Sub 频道定义（内部事件总线）
CHANNEL_MINUTE_BAR_READY = "intraday:minute_bar.ready"  # 分钟线就绪事件
CHANNEL_TICK_ANOMALY = "intraday:tick_anomaly"  # Tick 异动事件
CHANNEL_CONTROL = "intraday.control"  # 控制信号（start/stop）
CHANNEL_STATUS = "intraday.status"  # 监控任务状态变更
CHANNEL_INTRADAY_SIGNAL = "intraday:signal"  # 分时信号事件（5类核心信号）

# WebSocket 推送频道（前端订阅）
WS_TOPIC_MINUTE_BAR = "ws.intraday.minute_bar"
WS_TICK_ANOMALY = "ws.intraday.tick_anomaly"
WS_STATUS = "ws.intraday.status"
WS_TOPIC_INTRADAY_SIGNAL = "ws.intraday.signal"


def publish_minute_bar_ready(symbol: str, trade_time: str, bar: dict[str, Any]) -> None:
    """发布分钟线就绪事件"""
    payload = {"symbol": symbol, "trade_time": trade_time, "bar": bar}
    redis_client.publish(CHANNEL_MINUTE_BAR_READY, payload)
    redis_client.publish(f"{CHANNEL_PREFIX}{WS_TOPIC_MINUTE_BAR}", {
        "type": "UPDATE",
        "data": payload,
    })


def publish_tick_anomaly(symbol: str, anomaly_type: str, detail: dict[str, Any]) -> None:
    """发布 Tick 异动事件"""
    payload = {"symbol": symbol, "anomaly_type": anomaly_type, "detail": detail}
    redis_client.publish(CHANNEL_TICK_ANOMALY, payload)
    redis_client.publish(f"{CHANNEL_PREFIX}{WS_TICK_ANOMALY}", {
        "type": "UPDATE",
        "data": payload,
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
    redis_client.publish(f"{CHANNEL_PREFIX}{WS_STATUS}", {
        "type": "UPDATE",
        "data": message,
    })
    logger.info("监控任务状态变更: status=%s", status)


def publish_intraday_signal(signal: dict[str, Any]) -> None:
    """发布分时信号事件（5类核心信号）

    同时发布到：
    1. 内部事件总线 CHANNEL_INTRADAY_SIGNAL（服务间解耦）
    2. WebSocket 推送频道 WS_TOPIC_INTRADAY_SIGNAL（前端实时接收）

    Args:
        signal: 信号字典，字段对齐 TradingSignal.to_dict() + name
            必填: symbol, signal_type, direction, signal_source
            可选: name, strength, trade_time, raw_values, signal_id
    """
    redis_client.publish(CHANNEL_INTRADAY_SIGNAL, signal)
    redis_client.publish(f"{CHANNEL_PREFIX}{WS_TOPIC_INTRADAY_SIGNAL}", {
        "type": "UPDATE",
        "data": signal,
    })
