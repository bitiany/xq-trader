"""WebSocket Topic调度器（APScheduler）— 按订阅状态动态启停"""

from __future__ import annotations

import asyncio
import concurrent.futures

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.interval import IntervalTrigger  # type: ignore[import-untyped]

from framework.commons.logger import get_logger
from framework.ws.connection_manager import connection_manager
from framework.ws.publisher import ws_publisher
from framework.ws.redis_listener import redis_listener

from .spi import PrefixTopicSpi, SpiRegistry, TopicSpi

# 导入SPI实现以触发注册
from .spi.impl import BrokerStatusSpi, PnlSpi, StockQuoteSpi, WatchlistQuotesSpi  # noqa: F401

logger = get_logger("ws.scheduler")

TOPIC_JOB_INTERVAL = 2


class WsTopicScheduler:
    """WebSocket Topic调度器 — 按topic订阅状态动态启停APScheduler任务

    支持两种 SPI 模式：
    - 精确匹配（TopicSpi）：每个 topic 独立 job
    - 前缀匹配（PrefixTopicSpi）：同一前缀共用一个单例 job，批量处理所有被订阅的 topic
    """

    _scheduler: AsyncIOScheduler | None = None
    _running: bool = False
    # 所有被订阅的 topic（含 symbol），前缀 SPI 据此筛选当前需处理的 topics
    _active_topics: set[str] = set()
    # 已启动的 job key 集合（精确 topic 或前缀），用于实现前缀 SPI 单例 job
    _active_jobs: set[str] = set()
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
            cls._active_jobs.clear()
            redis_listener.stop()
            logger.info("WebSocket Scheduler stopped")

    @classmethod
    def on_topic_subscribed(cls, topic: str) -> None:
        """有连接订阅了topic，启动对应的定时任务

        前缀 SPI 单例 job：同一前缀下所有 topic 共用一个 job，避免大量 job。
        """
        if not cls._running or not cls._scheduler:
            return

        spi_cls = SpiRegistry.get(topic)
        if spi_cls is None:
            logger.warning(f"No SPI registered for topic: {topic}")
            return

        # 记录所有被订阅的 topic（前缀 SPI 据此筛选需处理的 topics）
        cls._active_topics.add(topic)

        # 用 job_key（精确 topic 或前缀）实现单例 job
        job_key = SpiRegistry.get_job_key(topic)
        if job_key is None or job_key in cls._active_jobs:
            return

        cls._active_jobs.add(job_key)
        job_id = f"ws_topic_{job_key}"

        cls._scheduler.add_job(
            cls._execute_spi,
            trigger=IntervalTrigger(seconds=TOPIC_JOB_INTERVAL),
            id=job_id,
            name=f"Topic: {job_key}",
            replace_existing=True,
            args=[job_key],
        )
        logger.info(f"Topic job started: {job_key}")

    @classmethod
    def on_topic_unsubscribed(cls, topic: str) -> None:
        """所有连接都取消了topic订阅，停止对应的定时任务

        前缀 SPI：只有当该前缀下所有 topic 都无订阅时才停 job。
        """
        if not cls._running or not cls._scheduler:
            return

        cls._active_topics.discard(topic)

        job_key = SpiRegistry.get_job_key(topic)
        if job_key is None:
            return

        # 前缀 SPI：检查该 job_key 下是否还有活跃 topic
        still_active = any(
            SpiRegistry.get_job_key(t) == job_key
            for t in cls._active_topics
        )
        if still_active:
            return

        cls._active_jobs.discard(job_key)
        job_id = f"ws_topic_{job_key}"

        try:
            cls._scheduler.remove_job(job_id)
            logger.info(f"Topic job stopped: {job_key}")
        except Exception as e:
            logger.warning("移除 Topic 任务失败: job_id=%s error=%s", job_id, e, exc_info=True)

    @classmethod
    async def _execute_spi(cls, job_key: str) -> None:
        """执行单个job的SPI并发布结果

        精确 SPI：job_key == topic，调用 execute()，单条 publish_update。
        前缀 SPI：job_key == prefix，筛选匹配的 active_topics，调用 execute_for_topics()，按 topic 分别 publish。
        """
        if not cls._running or not cls._executor:
            return

        try:
            # 判断是前缀 SPI 还是精确 SPI
            prefix_spi_cls = SpiRegistry.get_prefix_spi(job_key)
            if prefix_spi_cls is not None:
                await cls._execute_prefix_spi(prefix_spi_cls, job_key)
                return

            spi_cls = SpiRegistry.get(job_key)
            if spi_cls is None or not issubclass(spi_cls, TopicSpi):
                return
            await cls._execute_exact_spi(spi_cls, job_key)
        except Exception:
            # 定时任务不应因单次 SPI 失败而中断，log 后吞掉
            logger.error("SPI execution failed: job_key=%s", job_key, exc_info=True)

    @classmethod
    async def _execute_exact_spi(cls, spi_cls: type[TopicSpi], topic: str) -> None:
        """执行精确匹配 SPI"""
        spi = spi_cls()
        try:
            if hasattr(spi, "execute_async"):
                result = await asyncio.wait_for(spi.execute_async(), timeout=10)  # type: ignore[attr-defined]
            else:
                if cls._executor is None:
                    logger.error("Executor not initialized")
                    return
                future = cls._executor.submit(spi.execute)
                result = future.result(timeout=10)
        except asyncio.TimeoutError:
            logger.warning("SPI execution timeout (10s): topic=%s", topic)
            return
        except concurrent.futures.TimeoutError:
            logger.warning("SPI execution timeout (10s), cancelled: topic=%s", topic)
            return
        ws_publisher.publish_update(topic, result)

    @classmethod
    async def _execute_prefix_spi(cls, spi_cls: type[PrefixTopicSpi], prefix: str) -> None:
        """执行前缀匹配 SPI（单例 job，批量处理所有被订阅的 topic）"""
        topics = [t for t in cls._active_topics if t.startswith(prefix)]
        if not topics:
            return

        spi = spi_cls()
        try:
            if hasattr(spi, "execute_for_topics_async"):
                results = await asyncio.wait_for(spi.execute_for_topics_async(topics), timeout=10)  # type: ignore[attr-defined]
            else:
                if cls._executor is None:
                    logger.error("Executor not initialized")
                    return
                future = cls._executor.submit(spi.execute_for_topics, topics)
                results = future.result(timeout=10)
        except asyncio.TimeoutError:
            logger.warning("SPI execution timeout (10s): prefix=%s", prefix)
            return
        except concurrent.futures.TimeoutError:
            logger.warning("SPI execution timeout (10s), cancelled: prefix=%s", prefix)
            return
        for topic, data in results.items():
            ws_publisher.publish_update(topic, data)

    @classmethod
    def get_active_topics(cls) -> set[str]:
        return cls._active_topics.copy()

    @classmethod
    def get_active_jobs(cls) -> set[str]:
        return cls._active_jobs.copy()
