"""消息发布器"""

from __future__ import annotations

import json
import time
from typing import Any

from framework.commons.logger import get_logger
from framework.commons.redis_client import redis_client
from framework.ws.exceptions import WsPublishError
from framework.ws.messages import CHANNEL_PREFIX, WsServerMessageType

logger = get_logger("ws.publisher")


class WsPublisher:
    """WebSocket消息发布器"""

    @staticmethod
    def publish(topic: str, data: Any, msg_type: str = WsServerMessageType.UPDATE) -> None:
        """发布消息到Redis Pub/Sub并更新快照缓存"""
        try:
            message = {
                "topic": topic,
                "type": msg_type,
                "data": data,
                "timestamp": time.time(),
            }
            redis_client.publish(f"{CHANNEL_PREFIX}{topic}", message)

            snapshot_key = f"{CHANNEL_PREFIX}{topic}:snapshot"
            redis_client.set(snapshot_key, json.dumps(data, ensure_ascii=False))

            logger.debug(f"Published {msg_type} to {topic}")
        except WsPublishError:
            raise
        except Exception as e:
            raise WsPublishError(f"Failed to publish {msg_type} to {topic}") from e

    @classmethod
    def publish_update(cls, topic: str, data: Any) -> None:
        """发布增量更新消息"""
        cls.publish(topic, data, WsServerMessageType.UPDATE)

    @classmethod
    def publish_snapshot(cls, topic: str, data: Any) -> None:
        """发布快照消息"""
        cls.publish(topic, data, WsServerMessageType.SNAPSHOT)


ws_publisher = WsPublisher()
