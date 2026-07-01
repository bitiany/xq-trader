"""Redis Pub/Sub监听器"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

from framework.commons.logger import get_logger
from framework.commons.redis_client import redis_client
from framework.ws.connection_manager import connection_manager
from framework.ws.messages import CHANNEL_PREFIX, WsServerMessage, WsServerMessageType

logger = get_logger("ws.redis_listener")


class RedisListener:
    """Redis Pub/Sub监听器（后台线程）"""

    _instance: RedisListener | None = None

    def __new__(cls) -> RedisListener:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._running = False
        self._thread: threading.Thread | None = None
        self._pubsub: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        logger.info("RedisListener initialized")

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = asyncio.get_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("RedisListener started")

    def stop(self) -> None:
        self._running = False
        pubsub = self._pubsub
        if pubsub is not None:
            try:
                pubsub.punsubscribe()
            except Exception:
                logger.debug("RedisListener punsubscribe 失败", exc_info=True)
            try:
                pubsub.close()
            except Exception:
                logger.debug("RedisListener pubsub 关闭失败", exc_info=True)
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)

    def _run(self) -> None:
        try:
            self._pubsub = redis_client.pubsub()
            self._pubsub.psubscribe(f"{CHANNEL_PREFIX}*")
            logger.info("Listening to Redis Pub/Sub")

            for message in self._pubsub.listen():
                if not self._running:
                    break
                if message.get("type") == "pmessage":
                    self._handle_message(message)
        except OSError as e:
            # stop() 关闭 pubsub 时 listen() 可能抛出 WinError 10038，属正常关闭路径
            if self._running:
                logger.error("RedisListener 套接字异常: %s", e, exc_info=True)
            else:
                logger.debug("RedisListener 关闭中: %s", e)
        except Exception:
            if self._running:
                logger.error("RedisListener 异常退出", exc_info=True)
            else:
                logger.debug("RedisListener 关闭", exc_info=True)
        finally:
            self._pubsub = None
            logger.info("RedisListener stopped")

    def _handle_message(self, message: dict) -> None:
        try:
            channel = message.get("channel", "")
            data_str = message.get("data", "")
            if not channel or not data_str:
                return

            topic = channel.removeprefix(CHANNEL_PREFIX)
            data = json.loads(data_str)

            ws_msg = WsServerMessage(
                type=WsServerMessageType(data.get("type", "UPDATE")),
                channel=topic,
                data=data.get("data"),
            )

            loop = self._loop
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    connection_manager.broadcast_to_topic(topic, ws_msg),
                    loop,
                )
        except Exception:
            logger.warning("Redis 消息处理失败", exc_info=True)


redis_listener = RedisListener()
