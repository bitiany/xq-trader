"""分钟线合成器 - 接收 QMT 回调，组装 1m OHLCV 并批量落库

QMT subscribe_quote(period='1m') 的回调在 QMT 内部线程中执行，
本模块通过 asyncio.run_coroutine_threadsafe 桥接到主事件循环批量落库。

设计要点：
- 批量写入：每 _BATCH_INTERVAL 秒聚合一批写入 DB，避免每根分钟线单独写入
- 幂等：使用 bulk_create_or_update + on_conflict(symbol, trade_time)
- Redis 缓存最后处理的分钟时间戳，支持断点续传
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from framework.commons.redis_client import redis_client
from xqtrader.broker.services.qmt_data_collector import convert_symbol_from_qmt
from xqtrader.domain.market.models.candlestick import CandlestickMinute

logger = logging.getLogger("INTRADAY.COLLECTOR")

_BATCH_INTERVAL = 5  # 批量写入间隔（秒）
_LAST_TS_KEY = "intraday:minute_bar:last_ts"  # Redis 缓存的最后处理时间戳


class MinuteBarCollector:
    """分钟线合成器与批量落库

    线程模型：
    - on_bar_callback 由 QMT 内部线程调用，通过 threading.Lock 保护缓冲区写入
    - _flush_loop 在 asyncio 事件循环中运行，每 5s 批量落库
    - threading.Lock 跨线程同步，确保 list()+clear() 原子性，避免丢失并发写入
    """

    def __init__(self) -> None:
        # 待写入缓冲区 {symbol_trade_time: CandlestickMinute}
        self._buffer: dict[str, CandlestickMinute] = {}
        # 使用 threading.Lock 而非 asyncio.Lock，因为 on_bar_callback 是同步函数，
        # 在 QMT 内部线程中执行，asyncio.Lock 无法在同步上下文中使用
        self._buffer_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        """启动批量写入循环"""
        if self._running:
            logger.warning("MinuteBarCollector 已在运行，跳过启动")
            return
        self._loop = asyncio.get_running_loop()
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("MinuteBarCollector 已启动, batch_interval=%ss", _BATCH_INTERVAL)

    async def stop(self) -> None:
        """停止并刷新剩余缓冲区"""
        if not self._running:
            return
        self._running = False
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        # 最后刷新一次
        await self._flush_buffer()
        logger.info("MinuteBarCollector 已停止")

    def on_bar_callback(self, stock_code: str, bar_data: dict[str, Any]) -> None:
        """QMT subscribe_quote 回调（在 QMT 内部线程中执行）

        Args:
            stock_code: 证券代码，如 "SH.600000"
            bar_data: QMT 返回的 bar 字典，包含 time/open/high/low/close/volume/amount
        """
        try:
            bar = self._parse_bar(stock_code, bar_data)
            if bar is None:
                return
            # 写入缓冲区（threading.Lock 保护跨线程写操作）
            key = f"{bar.symbol}_{bar.trade_time.isoformat()}"
            with self._buffer_lock:
                self._buffer[key] = bar
        except Exception as e:
            logger.error("解析分钟线失败: %s, bar=%s, error=%s", stock_code, bar_data, e, exc_info=True)

    @staticmethod
    def _parse_bar(stock_code: str, bar_data: dict[str, Any]) -> CandlestickMinute | None:
        """解析 QMT bar 数据为 CandlestickMinute 实例

        QMT 时间戳为毫秒级 epoch，需转换为 UTC datetime
        """
        # 证券代码转换：SH.600000 -> 600000.SH（复用 qmt_data_collector 的转换函数）
        symbol = convert_symbol_from_qmt(stock_code)
        if "." not in symbol:
            logger.warning("无法解析证券代码: %s", stock_code)
            return None

        # 时间戳转换：QMT 返回毫秒级 epoch
        timestamp = bar_data.get("time")
        if timestamp is None:
            logger.warning("bar 数据缺少 time 字段: %s", stock_code)
            return None
        # QMT 时间戳为本地时间（北京时间），需明确处理
        # timestamp 单位为秒（浮点）或毫秒（整数）
        if isinstance(timestamp, (int, float)):
            if timestamp > 1e12:  # 毫秒级
                timestamp = timestamp / 1000.0
            trade_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        else:
            logger.warning("无法解析时间戳: %s, type=%s", timestamp, type(timestamp))
            return None

        trade_date = trade_time.date()

        return CandlestickMinute(
            symbol=symbol,
            trade_time=trade_time,
            open=float(bar_data.get("open", 0)),
            high=float(bar_data.get("high", 0)),
            low=float(bar_data.get("low", 0)),
            close=float(bar_data.get("close", 0)),
            volume=int(bar_data.get("volume", 0)),
            amount=float(bar_data.get("amount", 0)),
            trade_date=trade_date,
            data_source="qmt",
        )

    async def _flush_loop(self) -> None:
        """批量写入循环：每 _BATCH_INTERVAL 秒刷新一次缓冲区"""
        while self._running:
            try:
                await asyncio.sleep(_BATCH_INTERVAL)
                await self._flush_buffer()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("分钟线批量写入异常: %s", e, exc_info=True)
                await asyncio.sleep(1)  # 异常后短暂等待避免空转

    async def _flush_buffer(self) -> int:
        """刷新缓冲区到数据库

        Returns:
            写入的记录数
        """
        # threading.Lock 保护的临界区：list+clear 原子执行，避免并发写入丢失
        with self._buffer_lock:
            if not self._buffer:
                return 0
            instances = list(self._buffer.values())
            self._buffer.clear()

        if not instances:
            return 0

        # 按最后一条的 trade_time 更新 Redis 缓存（断点续传）
        last_ts = max(inst.trade_time for inst in instances)
        try:
            redis_client.set(_LAST_TS_KEY, last_ts.isoformat())
        except Exception as e:
            logger.warning("更新 Redis 缓存时间戳失败: %s", e)

        try:
            count = await CandlestickMinute.bulk_create_or_update(
                instances,
                on_conflict=["symbol", "trade_time"],
                update_fields=["open", "high", "low", "close", "volume", "amount",
                               "trade_date", "data_source"],
                batch_size=1000,
            )
            logger.debug("分钟线批量写入: count=%d, last_ts=%s", count, last_ts.isoformat())
            return count
        except Exception as e:
            logger.error("分钟线批量写入失败: count=%d, error=%s", len(instances), e, exc_info=True)
            # 失败时回填缓冲区（保留数据，下次重试）
            with self._buffer_lock:
                for inst in instances:
                    key = f"{inst.symbol}_{inst.trade_time.isoformat()}"
                    self._buffer[key] = inst
            return 0

    @staticmethod
    def get_last_timestamp() -> datetime | None:
        """获取最后处理的分钟时间戳（断点续传用）"""
        try:
            ts_str = redis_client.get(_LAST_TS_KEY)
            if ts_str:
                return datetime.fromisoformat(ts_str)
        except Exception as e:
            logger.warning("读取 Redis 缓存时间戳失败: %s", e)
        return None
