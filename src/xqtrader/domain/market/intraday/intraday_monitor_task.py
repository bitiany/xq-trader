"""盘内监控主任务 - FastAPI lifespan 内常驻 asyncio 后台任务

设计要点：
- 监听 Redis intraday.control 频道，收到 start 信号后启动 QMT 订阅
- 启动 MinuteBarCollector（分钟线合成+批量落库）
- 启动 TickAnomalyScanner（全推快照异动扫描，内存不落库）
- 收到 stop 信号后优雅停止订阅
- 任务幂等可重入：FastAPI 重启后从 Redis 缓存读最后时间戳恢复
- 异常自动重启：任务异常后 5s 重试

线程模型：
- 主任务在 asyncio 事件循环中运行（FastAPI lifespan 注册）
- QMT subscribe_quote 回调在 QMT 内部线程中执行
- 通过 IntradaySubscriptionManager 桥接回调与事件发布
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

from framework.commons.logger import get_logger
from framework.commons.redis_client import redis_client
from framework.dal.enginee import engines_manager
from xqtrader.broker.services.qmt_data_collector import QmtDataCollector
from xqtrader.domain.market.intraday.continuous_aggregate_setup import setup_continuous_aggregates
from xqtrader.domain.market.intraday.dynamic_pool import load_dynamic_stock_pool
from xqtrader.domain.market.intraday.minute_bar_collector import MinuteBarCollector
from xqtrader.domain.market.intraday.publishers import (
    CHANNEL_CONTROL,
    publish_status,
)
from xqtrader.domain.market.intraday.signal_generator import IntradaySignalGenerator
from xqtrader.domain.market.intraday.subscription_manager import IntradaySubscriptionManager
from xqtrader.domain.market.intraday.tick_anomaly_scanner import TickAnomalyScanner

logger = get_logger("INTRADAY.TASK")

_RESTART_DELAY = 5  # 异常重启延迟（秒）


class IntradayMonitorTask:
    """盘内监控主任务（单例）

    在 FastAPI lifespan 中注册，监听 Redis intraday.control 控制信号：
    - "start": 加载动态股票池 -> 启动 Collector/Scanner -> 委托 SubscriptionManager 订阅 QMT
    - "stop": 取消订阅 -> 刷新缓冲区
    """

    _instance: IntradayMonitorTask | None = None
    _lock = threading.Lock()

    def __new__(cls) -> IntradayMonitorTask:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        self._collector = MinuteBarCollector()
        self._scanner = TickAnomalyScanner()
        self._qmt = QmtDataCollector()
        self._subscription_manager = IntradaySubscriptionManager(
            self._qmt, self._collector, self._scanner,
        )
        self._signal_generator = IntradaySignalGenerator.get_instance()

        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._monitoring = False  # 是否正在监控（收到 start 后为 True）
        self._ca_initialized = False  # Continuous Aggregate 是否已初始化
        self._loop: asyncio.AbstractEventLoop | None = None

    @classmethod
    def get_instance(cls) -> IntradayMonitorTask:
        """获取单例"""
        return cls()

    @property
    def is_running(self) -> bool:
        """后台任务是否运行中"""
        return self._running

    @property
    def is_monitoring(self) -> bool:
        """是否正在监控（收到 start 信号后为 True）"""
        return self._monitoring

    async def start(self) -> None:
        """启动后台任务（FastAPI lifespan 调用）"""
        if self._running:
            logger.warning("IntradayMonitorTask 已在运行，跳过启动")
            return
        self._running = True
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._run())
        logger.info("IntradayMonitorTask 后台任务已启动")

    async def stop(self) -> None:
        """停止后台任务（FastAPI shutdown 调用）"""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self.stop_monitoring()
        logger.info("IntradayMonitorTask 后台任务已停止")

    async def _run(self) -> None:
        """主循环：监听 Redis 控制信号，异常自动重启"""
        while self._running:
            try:
                await self._listen_control()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("监控任务异常，%ss 后重启: %s", _RESTART_DELAY, e, exc_info=True)
                publish_status("error", {"message": str(e)})
                await asyncio.sleep(_RESTART_DELAY)

    async def _listen_control(self) -> None:
        """监听 Redis intraday.control 频道

        使用 loop.run_in_executor 在线程中运行阻塞式 pubsub.listen()，
        通过 asyncio.run_coroutine_threadsafe 桥接到事件循环处理消息。
        """
        pubsub = redis_client.pubsub()
        pubsub.subscribe(CHANNEL_CONTROL)
        logger.info("开始监听控制信号: channel=%s", CHANNEL_CONTROL)

        loop = asyncio.get_running_loop()
        # 用于从线程向事件循环传递消息
        message_queue: asyncio.Queue[dict] = asyncio.Queue()

        def _blocking_listen() -> None:
            """在单独线程中阻塞式监听 Redis PubSub"""
            try:
                for message in pubsub.listen():
                    if not self._running:
                        break
                    if message.get("type") == "message":
                        asyncio.run_coroutine_threadsafe(
                            message_queue.put(message), loop
                        )
            except Exception as e:
                logger.error("PubSub 监听线程异常: %s", e, exc_info=True)

        # 启动监听线程
        listener_future = loop.run_in_executor(None, _blocking_listen)

        try:
            while self._running:
                # 非阻塞从队列获取消息，超时后重试
                try:
                    message = await asyncio.wait_for(message_queue.get(), timeout=1.0)
                    await self._handle_control_message(message.get("data"))
                except asyncio.TimeoutError:
                    continue
        finally:
            pubsub.unsubscribe(CHANNEL_CONTROL)
            pubsub.close()
            listener_future.cancel()

    async def _handle_control_message(self, raw_data: Any) -> None:
        """处理控制消息

        Args:
            raw_data: Redis PubSub 返回的消息数据，通常为 bytes（json.dumps 后的字节串）
        """
        try:
            # json.loads 直接支持 bytes/str（Python 3.6+）
            data = json.loads(raw_data) if isinstance(raw_data, (str, bytes, bytearray)) else raw_data
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("无法解析控制消息: %s, error=%s", raw_data, e)
            return

        if not isinstance(data, dict):
            logger.warning("控制消息格式错误，期望 dict: %s", type(data))
            return

        action = data.get("action")
        logger.info("收到控制信号: action=%s, data=%s", action, data)

        if action == "start":
            await self.start_monitoring()
        elif action == "stop":
            await self.stop_monitoring()
        else:
            logger.warning("未知控制信号: action=%s", action)

    async def start_monitoring(self) -> None:
        """启动监控：连接行情 -> 初始化CA -> 加载股票池 -> 启动 Collector/Scanner -> 委托 SubscriptionManager 订阅"""
        if self._monitoring:
            logger.warning("监控已在运行，跳过启动")
            return

        # 0. 连接 QMT 行情服务（subscribe_quote 前置条件）
        await self._qmt.connect()

        # 0.5 初始化 Continuous Aggregate（首次启动时，此时数据源已就绪）
        if not self._ca_initialized:
            try:
                stock_engine = engines_manager.get_engine("stock")
                await setup_continuous_aggregates(stock_engine)
                self._ca_initialized = True
            except Exception as e:
                logger.error("Continuous Aggregate 初始化失败: %s", e, exc_info=True)

        # 1. 加载动态股票池
        symbols = await load_dynamic_stock_pool()
        if not symbols:
            logger.warning("动态股票池为空，跳过监控启动")
            return

        # 2. 启动 Collector（批量落库循环）
        await self._collector.start()

        # 3. 启动 Scanner
        self._scanner.start()

        # 3.5 设置事件循环引用（用于异动落库的线程安全桥接）
        self._subscription_manager.set_event_loop(asyncio.get_running_loop())

        # 4. 委托 SubscriptionManager 订阅 QMT 分钟线+全推快照
        try:
            self._subscription_manager.start_subscriptions(symbols)
        except Exception as e:
            logger.error("订阅 QMT 失败: %s", e, exc_info=True)
            await self.stop_monitoring()
            raise RuntimeError(f"QMT 订阅失败: {e}") from e

        self._monitoring = True
        publish_status("started", {"symbols_count": len(symbols)})
        logger.info("盘内监控已启动: symbols=%d", len(symbols))

        # 5. 启动信号生成器（监听异动事件 -> 自动创建 PreOrder -> 提交执行）
        await self._signal_generator.start()

    async def stop_monitoring(self) -> None:
        """停止监控：停止信号生成器 -> 取消订阅 -> 停止 Scanner/Collector"""
        if not self._monitoring:
            return
        self._monitoring = False

        # 停止信号生成器
        await self._signal_generator.stop()

        # 取消 QMT 订阅
        self._subscription_manager.stop_subscriptions()

        # 停止 Scanner
        self._scanner.stop()

        # 停止 Collector（刷新剩余缓冲区）
        await self._collector.stop()

        publish_status("stopped")
        logger.info("盘内监控已停止")
