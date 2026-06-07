"""WebSocket Topic调度器（APScheduler）— 按订阅状态动态启停"""

from __future__ import annotations

import concurrent.futures

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from framework.commons.logger import get_logger
from framework.ws.connection_manager import connection_manager
from framework.ws.exceptions import WsSpiError
from framework.ws.publisher import ws_publisher
from framework.ws.redis_listener import redis_listener

from .spi import SpiRegistry

# 导入SPI实现以触发注册
from .spi.impl import BrokerStatusSpi, PnlSpi  # noqa: F401

logger = get_logger("ws.scheduler")

TOPIC_JOB_INTERVAL = 2


class WsTopicScheduler:
    """WebSocket Topic调度器 — 按topic订阅状态动态启停APScheduler任务"""

    _scheduler: AsyncIOScheduler | None = None
    _running: bool = False
    _active_topics: set[str] = set()
    _executor: concurrent.futures.ThreadPoolExecutor | None = None

    @classmethod
    def start(cls) -> None:
        """应用启动时初始化APScheduler（不添加任何job）"""
        if cls._running:
            return

        redis_listener.start()

        cls._scheduler = AsyncIOScheduler()
        cls._scheduler.start()
        cls._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        cls._running = True

        # 注册回调：framework层通过回调通知scheduler，不反向依赖
        connection_manager.set_topic_callbacks(
            on_subscribed=cls.on_topic_subscribed,
            on_unsubscribed=cls.on_topic_unsubscribed,
        )

        logger.info("WebSocket Scheduler initialized (no active topics)")

    @classmethod
    def stop(cls) -> None:
        """应用关闭时停止APScheduler"""
        if cls._scheduler and cls._running:
            cls._scheduler.shutdown()
            if cls._executor:
                cls._executor.shutdown(wait=False)
            cls._running = False
            cls._active_topics.clear()
            redis_listener.stop()
            logger.info("WebSocket Scheduler stopped")

    @classmethod
    def on_topic_subscribed(cls, topic: str) -> None:
        """有连接订阅了topic，启动对应的定时任务"""
        if not cls._running or not cls._scheduler:
            return

        if topic in cls._active_topics:
            return

        spi_cls = SpiRegistry.get(topic)
        if spi_cls is None:
            logger.warning(f"No SPI registered for topic: {topic}")
            return

        cls._active_topics.add(topic)
        job_id = f"ws_topic_{topic}"

        cls._scheduler.add_job(
            cls._execute_spi,
            trigger=IntervalTrigger(seconds=TOPIC_JOB_INTERVAL),
            id=job_id,
            name=f"Topic: {topic}",
            replace_existing=True,
            args=[topic],
        )
        logger.info(f"Topic job started: {topic}")

    @classmethod
    def on_topic_unsubscribed(cls, topic: str) -> None:
        """所有连接都取消了topic订阅，停止对应的定时任务"""
        if not cls._running or not cls._scheduler:
            return

        if topic not in cls._active_topics:
            return

        cls._active_topics.discard(topic)
        job_id = f"ws_topic_{topic}"

        try:
            cls._scheduler.remove_job(job_id)
            logger.info(f"Topic job stopped: {topic}")
        except WsSpiError:
            raise
        except Exception as e:
            logger.warning("移除 Topic 任务失败: topic=%s job_id=%s error=%s", topic, job_id, e)

    @classmethod
    async def _execute_spi(cls, topic: str) -> dict | None:
        """执行单个topic的SPI并发布结果"""
        spi_cls = SpiRegistry.get(topic)
        if spi_cls is None:
            return None

        try:
            spi = spi_cls()
            future = cls._executor.submit(spi.execute)
            result = future.result(timeout=10)
            ws_publisher.publish_update(topic, result)
            return result
        except WsSpiError:
            raise
        except Exception as e:
            raise WsSpiError(f"SPI {topic} execution failed") from e

    @classmethod
    def get_active_topics(cls) -> set[str]:
        return cls._active_topics.copy()
