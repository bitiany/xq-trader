"""WebSocket连接管理器"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from framework.commons.logger import get_logger
from framework.commons.redis_client import redis_client
from framework.ws.exceptions import WsConnectionError, WsMessageError
from framework.ws.messages import (
    SUBSCRIBERS_PREFIX,
    WsClientMessage,
    WsClientMethod,
    WsServerMessage,
    WsServerMessageType,
)

logger = get_logger("ws.manager")

# 心跳配置
HEARTBEAT_CHECK_INTERVAL = 30
HEARTBEAT_TIMEOUT = 60
SERVER_PING_INTERVAL = 25


class MessageHandler:
    """消息路由策略 — 按method分发到对应处理函数"""

    def __init__(self) -> None:
        self._handlers: dict[WsClientMethod, Callable[..., Any]] = {}

    def register(self, method: WsClientMethod, handler: Callable[..., Any]) -> None:
        self._handlers[method] = handler

    async def dispatch(self, conn_id: str, msg: WsClientMessage) -> None:
        handler = self._handlers.get(msg.method)
        if handler is None:
            raise WsMessageError(f"Unknown method: {msg.method}")
        await handler(conn_id, msg)


class ConnectionManager:
    """WebSocket连接管理器（单例）"""

    _instance: ConnectionManager | None = None

    def __new__(cls) -> ConnectionManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._connections: dict[str, WebSocket] = {}
        self._subscriptions: dict[str, set[str]] = {}  # conn_id -> set[topic]
        self._subscribers: dict[str, set[str]] = {}  # topic -> set[conn_id]
        self._last_active: dict[str, float] = {}
        self._heartbeat_task: asyncio.Task | None = None
        self._ping_task: asyncio.Task | None = None
        # 回调：由业务层注册，framework层不依赖xqtrader
        self._on_topic_subscribed: Callable[[str], None] | None = None
        self._on_topic_unsubscribed: Callable[[str], None] | None = None
        # 消息路由策略
        self._router = MessageHandler()
        self._router.register(WsClientMethod.SUBSCRIBE, self._handle_subscribe)
        self._router.register(WsClientMethod.UNSUBSCRIBE, self._handle_unsubscribe)
        self._router.register(WsClientMethod.PING, self._handle_ping)
        self._router.register(WsClientMethod.LIST_SUBSCRIPTIONS, self._handle_list_subscriptions)
        logger.info("ConnectionManager initialized")

    def set_topic_callbacks(
        self,
        on_subscribed: Callable[[str], None] | None = None,
        on_unsubscribed: Callable[[str], None] | None = None,
    ) -> None:
        """注册topic订阅/取消订阅回调（由业务层调用）"""
        self._on_topic_subscribed = on_subscribed
        self._on_topic_unsubscribed = on_unsubscribed

    async def start_heartbeat(self) -> None:
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        if self._ping_task is None:
            self._ping_task = asyncio.create_task(self._ping_loop())

    async def _heartbeat_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_CHECK_INTERVAL)
                now = time.time()
                for conn_id, last in list(self._last_active.items()):
                    if now - last > HEARTBEAT_TIMEOUT:
                        logger.warning(f"Connection {conn_id[:8]} timed out")
                        await self.disconnect(conn_id)
            except asyncio.CancelledError:
                break
            except Exception:
                # 单次心跳检查失败不应终止整个心跳任务（长任务必须保持运行）
                logger.warning("心跳检查异常", exc_info=True)

    async def _ping_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(SERVER_PING_INTERVAL)
                if not self._connections:
                    continue
                ping_msg = WsServerMessage(type=WsServerMessageType.PING)
                payload = ping_msg.model_dump(mode="json")
                tasks = []
                for conn_id in list(self._connections):
                    ws = self._connections.get(conn_id)
                    if ws:
                        tasks.append(self._safe_send_and_cleanup(conn_id, ws, payload))
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.CancelledError:
                break
            except Exception:
                # 单次 ping 失败不应终止整个 ping 任务
                logger.warning("服务端 ping 异常", exc_info=True)

    async def connect(self, websocket: WebSocket) -> str:
        conn_id = uuid4().hex
        await websocket.accept()
        self._connections[conn_id] = websocket
        self._subscriptions[conn_id] = set()
        self._last_active[conn_id] = time.time()
        logger.info(f"Connection {conn_id[:8]} established")
        return conn_id

    async def disconnect(self, conn_id: str) -> None:
        """断开连接，清理订阅并通知回调"""
        topics = list(self._subscriptions.get(conn_id, set()))
        for topic in topics:
            self._remove_subscription(conn_id, topic)

        ws = self._connections.pop(conn_id, None)
        self._subscriptions.pop(conn_id, None)
        self._last_active.pop(conn_id, None)

        if ws and ws.client_state == WebSocketState.CONNECTED:
            try:
                await ws.close()
            except Exception as e:
                # disconnect 是清理操作，关闭异常不应传播（避免心跳/ping 任务级联退出）
                logger.warning("关闭 WebSocket 连接异常: conn=%s error=%s", conn_id[:8], e, exc_info=True)

        logger.info(f"Connection {conn_id[:8]} disconnected, cleaned {len(topics)} subscriptions")

    async def send(self, conn_id: str, message: WsServerMessage) -> None:
        """发送消息到指定连接（公共接口）"""
        ws = self._connections.get(conn_id)
        if ws:
            await self._safe_send_and_cleanup(conn_id, ws, message.model_dump(mode="json"))

    async def handle_message(self, conn_id: str, raw: str) -> None:
        try:
            data = json.loads(raw)
            msg = WsClientMessage.model_validate(data)
        except Exception as e:
            raise WsMessageError("Invalid message format") from e

        self._last_active[conn_id] = time.time()

        try:
            await self._router.dispatch(conn_id, msg)
        except WsMessageError:
            raise
        except Exception as e:
            raise WsMessageError(f"Error handling message method={msg.method}") from e

    # ── 消息处理策略 ──

    async def _handle_subscribe(self, conn_id: str, msg: WsClientMessage) -> None:
        topics = self._parse_params(msg.params)
        for topic in topics:
            self._add_subscription(conn_id, topic)
        await self.send(conn_id, WsServerMessage(type=WsServerMessageType.ACK, id=msg.id, data=topics))

    async def _handle_unsubscribe(self, conn_id: str, msg: WsClientMessage) -> None:
        topics = self._parse_params(msg.params)
        for topic in topics:
            self._remove_subscription(conn_id, topic)
        await self.send(conn_id, WsServerMessage(type=WsServerMessageType.ACK, id=msg.id, data=topics))

    async def _handle_ping(self, conn_id: str, msg: WsClientMessage) -> None:
        await self.send(conn_id, WsServerMessage(type=WsServerMessageType.PONG, id=msg.id))

    async def _handle_list_subscriptions(self, conn_id: str, msg: WsClientMessage) -> None:
        subs = list(self._subscriptions.get(conn_id, set()))
        await self.send(conn_id, WsServerMessage(type=WsServerMessageType.RESULT, id=msg.id, data=subs))

    @staticmethod
    def _parse_params(params: Any) -> list[str]:
        """解析消息参数为topic列表"""
        if isinstance(params, list):
            return [str(p) for p in params]
        return [str(params)]

    # ── 订阅管理 ──

    def _add_subscription(self, conn_id: str, topic: str) -> None:
        self._subscriptions.setdefault(conn_id, set()).add(topic)
        self._subscribers.setdefault(topic, set()).add(conn_id)
        redis_key = f"{SUBSCRIBERS_PREFIX}{topic}:subscribers"
        redis_client.sadd(redis_key, conn_id)
        logger.debug(f"Conn {conn_id[:8]} subscribed {topic}")

        if self._on_topic_subscribed:
            self._on_topic_subscribed(topic)

    def _remove_subscription(self, conn_id: str, topic: str) -> None:
        self._subscriptions.get(conn_id, set()).discard(topic)
        topic_conns = self._subscribers.get(topic, set())
        topic_conns.discard(conn_id)

        if not topic_conns:
            self._subscribers.pop(topic, None)
            if self._on_topic_unsubscribed:
                self._on_topic_unsubscribed(topic)

        redis_key = f"{SUBSCRIBERS_PREFIX}{topic}:subscribers"
        redis_client.srem(redis_key, conn_id)
        logger.debug(f"Conn {conn_id[:8]} unsubscribed {topic}")

    # ── 广播 ──

    async def broadcast_to_topic(self, topic: str, message: WsServerMessage) -> None:
        conn_ids = list(self._subscribers.get(topic, set()))
        if not conn_ids:
            return
        payload = message.model_dump(mode="json")
        tasks = []
        for cid in conn_ids:
            ws = self._connections.get(cid)
            if ws:
                tasks.append(self._safe_send_and_cleanup(cid, ws, payload))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ── 发送 ──

    async def _safe_send_and_cleanup(self, conn_id: str, ws: WebSocket, data: dict) -> None:
        """安全发送消息，断连时自动清理"""
        try:
            await ws.send_json(data)
        except WebSocketDisconnect:
            logger.debug(f"Connection {conn_id[:8]} disconnected during send, cleaning up")
            await self.disconnect(conn_id)
        except WsConnectionError:
            raise
        except Exception as e:
            logger.debug(f"Send failed for {conn_id[:8]}: {e}")
            await self.disconnect(conn_id)


connection_manager = ConnectionManager()
