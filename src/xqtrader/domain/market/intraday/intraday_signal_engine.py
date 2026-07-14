"""分时信号引擎 — 监听分钟线就绪事件，计算 5 类核心信号并推送

职责：
1. 订阅 Redis `intraday:minute_bar.ready` 频道，每根 1m bar 就绪时触发计算
2. 加载该 symbol 当日全部 1m 分钟线作为计算上下文
3. 调用 signal_calculators 中注册的所有计算器，产出 SignalResult
4. 信号去重：同一 symbol 同一交易日，同一 signal_type 仅首次触发
5. 持久化到 TradingSignal 表（signal_source='intraday'）
6. 通过 publish_intraday_signal 推送 WS 消息到前端

线程模型：
- 主任务在 asyncio 事件循环中运行
- Redis pubsub.listen() 在单独线程中阻塞运行（run_in_executor）
- 通过 asyncio.Queue + run_coroutine_threadsafe 桥接消息
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from framework.commons.redis_client import redis_client
from framework.commons.time_util import today_shanghai
from xqtrader.domain.market.intraday.publishers import (
    CHANNEL_MINUTE_BAR_READY,
    publish_intraday_signal,
)
from xqtrader.domain.market.intraday.signal_calculators import (
    SignalContext,
    SignalResult,
    get_all_calculators,
)
from xqtrader.domain.market.models.candlestick import CandlestickMinute
from xqtrader.domain.security.models import Security
from xqtrader.domain.trading.enums import Direction, IntradaySignalType, SignalSource
from xqtrader.domain.trading.models.decision import TradingSignal

logger = logging.getLogger("INTRADAY.SIGNAL_ENGINE")

# 默认策略实例 ID（与 IntradaySignalGenerator 对齐）
_DEFAULT_INSTANCE_ID = 1

# 东八区时区（用于解析 QMT 时间戳）
_CST = timezone(timedelta(hours=8))

# 等待 Collector 落库的轮询参数
_BAR_WAIT_INTERVAL = 1.0  # 每次轮询间隔（秒）
_BAR_WAIT_MAX_RETRIES = 6  # 最多重试 6 次 × 1s = 6s（覆盖 Collector 5s 批量间隔 + 余量）


class IntradaySignalEngine:
    """分时信号引擎（单例）

    监听分钟线就绪事件，调度 5 类信号计算器，持久化并推送信号。
    与 IntradaySignalGenerator（异动→自动交易）解耦，本引擎仅产出分析信号，不触发交易。
    """

    _instance: IntradaySignalEngine | None = None

    @classmethod
    def get_instance(cls) -> IntradaySignalEngine:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._instance_id: int = _DEFAULT_INSTANCE_ID
        self._calculators = get_all_calculators()
        self._running: bool = False
        self._task: asyncio.Task[None] | None = None
        # 当日已触发信号去重：key = f"{symbol}:{trade_date}:{signal_type}"
        self._triggered_keys: set[str] = set()
        # 标的名称缓存，避免每次信号触发都查库
        self._name_cache: dict[str, str] = {}

    @property
    def is_running(self) -> bool:
        return self._running

    def configure(self, instance_id: int) -> None:
        """配置策略实例 ID"""
        self._instance_id = instance_id

    async def start(self) -> None:
        """启动信号引擎"""
        if self._running:
            logger.warning("分时信号引擎已在运行")
            return
        self._running = True
        self._triggered_keys.clear()
        self._name_cache.clear()
        self._task = asyncio.create_task(self._listen_minute_bars())
        logger.info(
            "分时信号引擎已启动: instance_id=%d, calculators=%d",
            self._instance_id, len(self._calculators),
        )

    async def stop(self) -> None:
        """停止信号引擎"""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("分时信号引擎已停止")

    async def _listen_minute_bars(self) -> None:
        """监听分钟线就绪事件

        使用 loop.run_in_executor 在线程中运行阻塞式 pubsub.listen()，
        通过 asyncio.Queue + run_coroutine_threadsafe 桥接到事件循环处理消息。

        包含重连机制：遇到 OSError（WinError 10038）等异常时自动重建 pubsub 连接。
        """
        loop = asyncio.get_running_loop()
        message_queue: asyncio.Queue[dict] = asyncio.Queue()

        def _blocking_listen() -> None:
            """在单独线程中阻塞式监听 Redis PubSub（带重连）"""
            while self._running:
                pubsub = redis_client.pubsub()
                try:
                    pubsub.subscribe(CHANNEL_MINUTE_BAR_READY)
                    logger.info("已订阅分钟线就绪事件: channel=%s", CHANNEL_MINUTE_BAR_READY)
                    for message in pubsub.listen():
                        if not self._running:
                            break
                        if message.get("type") == "message":
                            asyncio.run_coroutine_threadsafe(
                                message_queue.put(message), loop
                            )
                except Exception:
                    if self._running:
                        logger.error("分钟线就绪事件 PubSub 监听异常，3s 后重连", exc_info=True)
                        time.sleep(3)
                finally:
                    try:
                        pubsub.unsubscribe(CHANNEL_MINUTE_BAR_READY)
                        pubsub.close()
                    except Exception:
                        pass

        listener_future = loop.run_in_executor(None, _blocking_listen)

        try:
            while self._running:
                try:
                    message = await asyncio.wait_for(message_queue.get(), timeout=1.0)
                    raw = message.get("data")
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    data = json.loads(raw) if isinstance(raw, str) else raw
                    if isinstance(data, dict):
                        await self._handle_bar_ready(data)
                except asyncio.TimeoutError:
                    continue
        finally:
            listener_future.cancel()

    async def _handle_bar_ready(self, data: dict[str, Any]) -> None:
        """处理单条分钟线就绪事件

        Args:
            data: publish_minute_bar_ready 发布的 payload
                {symbol, trade_time, bar: {open, high, low, close, volume, amount}}

        注意：publish_minute_bar_ready 在 QMT 回调线程中同步发布，而 MinuteBarCollector
        的批量落库有 5s 延迟。通过轮询 DB 确认最新 bar 已写入，最多等待 6s。
        """
        symbol = data.get("symbol", "")
        if not symbol:
            return

        trade_date = today_shanghai()
        expected_trade_time = data.get("trade_time", "")

        # 轮询等待 Collector 批量落库完成：检查 DB 最新 bar 的 trade_time 是否 >= 事件 trade_time
        # 最多重试 6 次 × 1s = 6s（覆盖 Collector 5s 批量间隔 + 余量）
        bars = await self._wait_for_latest_bar(symbol, trade_date, expected_trade_time)
        if bars is None:
            logger.warning(
                "等待最新 bar 落库超时: symbol=%s, expected_trade_time=%s",
                symbol, expected_trade_time,
            )
            return

        if len(bars) < 2:
            return

        logger.info(
            "处理分钟线就绪事件: symbol=%s, bars=%d, trade_time=%s",
            symbol, len(bars), expected_trade_time,
        )

        # 获取标的名称（带缓存）
        name = self._name_cache.get(symbol)
        if name is None:
            sec = await Security.get_or_none(symbol=symbol)
            name = sec.name if sec and sec.name else symbol
            self._name_cache[symbol] = name

        ctx = SignalContext(
            symbol=symbol,
            name=name,
            bars=bars,
            trade_date=trade_date,
        )

        # 逐个计算器计算信号，收集本轮触发的信号
        triggered_this_bar: list[SignalResult] = []
        for calculator in self._calculators:
            try:
                result = calculator.calculate(ctx)
            except Exception:
                logger.error(
                    "信号计算异常: symbol=%s, calculator=%s",
                    symbol, calculator.__class__.__name__, exc_info=True,
                )
                continue
            if result is None:
                continue
            triggered_this_bar.append(result)
            await self._emit_signal(symbol, name, trade_date, result)

        # 共振检测：同一根 bar 有 2+ 信号同方向触发，生成共振信号
        if len(triggered_this_bar) >= 2:
            long_count = sum(1 for r in triggered_this_bar if r.direction == Direction.LONG)
            short_count = sum(1 for r in triggered_this_bar if r.direction == Direction.SHORT)
            # 同方向信号 >= 2 个才构成共振
            if long_count >= 2 or short_count >= 2:
                resonance_dir: str = Direction.LONG if long_count >= 2 else Direction.SHORT
                contributing_results = [r for r in triggered_this_bar if r.direction == resonance_dir]
                await self._emit_resonance_signal(
                    symbol, name, trade_date,
                    direction=resonance_dir,
                    contributing_results=contributing_results,
                    trade_time=triggered_this_bar[0].trade_time,
                )

    async def _wait_for_latest_bar(
        self,
        symbol: str,
        trade_date: Any,
        expected_trade_time: str,
    ) -> list[CandlestickMinute] | None:
        """轮询等待 Collector 批量落库完成，确保 DB 已包含事件对应的最新 bar。

        优化策略：轮询时只查最新 1 根 bar（desc + limit=1）判断是否到位，
        到位后再加载当日全量 bars 用于信号计算，避免每次轮询都加载全量数据。

        Args:
            symbol: 证券代码
            trade_date: 交易日期
            expected_trade_time: 事件中的 trade_time（QMT 时间戳字符串）

        Returns:
            当日全部 1m 分钟线列表（按 trade_time 升序）；超时返回 None
        """
        expected_dt = self._parse_trade_time(expected_trade_time)

        # 轮询：只查最新 1 根 bar 确认落库进度（避免每次加载全量 240 根）
        for _ in range(_BAR_WAIT_MAX_RETRIES):
            latest = await CandlestickMinute.filter(
                symbol=symbol,
                trade_date=trade_date,
                order_by=CandlestickMinute.trade_time.desc(),
                limit=1,
            )
            if latest:
                latest_dt = latest[0].trade_time
                if expected_dt is None or latest_dt >= expected_dt:
                    # 已到位，加载全量 bars 用于信号计算
                    return await CandlestickMinute.filter(
                        symbol=symbol,
                        trade_date=trade_date,
                        order_by=CandlestickMinute.trade_time.asc(),
                        limit=None,
                    )
            await asyncio.sleep(_BAR_WAIT_INTERVAL)

        # 超时：最后尝试加载全量数据（即使未达 expected，也尝试用现有数据计算）
        bars = await CandlestickMinute.filter(
            symbol=symbol,
            trade_date=trade_date,
            order_by=CandlestickMinute.trade_time.asc(),
            limit=None,
        )
        return bars if bars else None

    @staticmethod
    def _parse_trade_time(trade_time_str: str) -> datetime | None:
        """解析 QMT trade_time 字符串为东八区 datetime。

        QMT bar_data["time"] 可能为秒级或毫秒级时间戳。
        """
        if not trade_time_str:
            return None
        try:
            ts = float(trade_time_str)
            # 毫秒级时间戳（13 位）需除以 1000
            if ts > 1e12:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=_CST)
        except (ValueError, OSError):
            return None

    async def _emit_signal(
        self,
        symbol: str,
        name: str,
        trade_date: Any,
        result: SignalResult,
    ) -> None:
        """持久化信号并推送 WS

        去重策略：同一 symbol 同一交易日，同一 signal_type 仅首次触发。
        过滤策略：强度低于 0.1 的信号视为噪音，不触发。
        """
        # 过滤低强度噪音信号
        if result.strength < 0.1:
            return

        dedup_key = f"{symbol}:{trade_date.isoformat()}:{result.signal_type}"
        if dedup_key in self._triggered_keys:
            return
        self._triggered_keys.add(dedup_key)

        # 将 trade_time 注入 raw_values，确保 REST API 从 raw_values 提取时也能取到
        # （TradingSignal 表无独立 trade_time 字段，raw_values 为唯一持久化载体）
        raw_values = dict(result.raw_values)
        raw_values["trade_time"] = (
            result.trade_time.isoformat() if result.trade_time else None
        )

        # 持久化到 TradingSignal 表
        try:
            signal = await TradingSignal.create(
                instance_id=self._instance_id,
                signal_date=trade_date,
                symbol=symbol,
                direction=result.direction,
                strength=result.strength,
                signal_type=result.signal_type,
                signal_source=SignalSource.INTRADAY,
                raw_values=raw_values,
                node_id=f"intraday_signal_engine:{result.signal_type}",
            )
        except Exception:
            logger.error(
                "信号持久化失败: symbol=%s, type=%s",
                symbol, result.signal_type, exc_info=True,
            )
            return

        # 推送 WS（字段对齐前端 SignalItem + IntradaySignal 接口）
        payload = {
            "id": signal.id,
            "instance_id": signal.instance_id,
            "signal_date": trade_date.isoformat(),
            "symbol": symbol,
            "name": name,
            "direction": result.direction,
            "strength": result.strength,
            "signal_type": result.signal_type,
            "signal_source": SignalSource.INTRADAY,
            "raw_values": raw_values,
            "trade_time": result.trade_time.isoformat() if result.trade_time else None,
            "created_at": signal.created_at.isoformat() if signal.created_at else None,
        }
        try:
            publish_intraday_signal(payload)
        except Exception:
            logger.error(
                "信号 WS 推送失败: symbol=%s, type=%s",
                symbol, result.signal_type, exc_info=True,
            )

        direction_label = {
            Direction.LONG: "多",
            Direction.SHORT: "空",
            Direction.NEUTRAL: "中性",
        }.get(result.direction, result.direction)
        logger.info(
            "分时信号触发: symbol=%s, type=%s, direction=%s, strength=%.2f",
            symbol, result.signal_type, direction_label, result.strength,
        )

    async def _emit_resonance_signal(
        self,
        symbol: str,
        name: str,
        trade_date: Any,
        direction: str,
        contributing_results: list[SignalResult],
        trade_time: Any,
    ) -> None:
        """共振信号：同一根 bar 有 2+ 信号同方向触发

        共振信号比单一信号更有参考价值，表示多维度指标一致看多/看空。
        去重：同一 symbol 同一交易日，仅首次共振触发。
        raw_values.contributing 包含每个信号的类型、方向与关键数据，供前端精确展示。
        """
        resonance_key = f"{symbol}:{trade_date.isoformat()}:resonance"
        if resonance_key in self._triggered_keys:
            return
        self._triggered_keys.add(resonance_key)

        signal_type = IntradaySignalType.RESONANCE
        strength = min(len(contributing_results) / 5.0, 1.0)  # 共振指标数越多强度越高

        # 为每个 contributing 信号提取关键展示数据（type + direction + 关键指标值）
        contributing = [_extract_signal_brief(r) for r in contributing_results]
        contributing_types = [r.signal_type for r in contributing_results]

        raw_values = {
            "contributing": contributing,
            "contributing_types": contributing_types,
            "count": len(contributing_results),
            "trade_time": trade_time.isoformat() if trade_time else None,
        }

        try:
            signal = await TradingSignal.create(
                instance_id=self._instance_id,
                signal_date=trade_date,
                symbol=symbol,
                direction=direction,
                strength=strength,
                signal_type=signal_type,
                signal_source=SignalSource.INTRADAY,
                raw_values=raw_values,
                node_id="intraday_signal_engine:resonance",
            )
        except Exception:
            logger.error(
                "共振信号持久化失败: symbol=%s", symbol, exc_info=True,
            )
            return

        payload = {
            "id": signal.id,
            "instance_id": signal.instance_id,
            "signal_date": trade_date.isoformat(),
            "symbol": symbol,
            "name": name,
            "direction": direction,
            "strength": strength,
            "signal_type": signal_type,
            "signal_source": SignalSource.INTRADAY,
            "raw_values": raw_values,
            "resonance": contributing_types,
            "trade_time": trade_time.isoformat() if trade_time else None,
            "created_at": signal.created_at.isoformat() if signal.created_at else None,
        }
        try:
            publish_intraday_signal(payload)
        except Exception:
            logger.error("共振信号 WS 推送失败: symbol=%s", symbol, exc_info=True)

        direction_label = "多" if direction == Direction.LONG else "空"
        logger.info(
            "共振信号触发: symbol=%s, direction=%s, strength=%.2f, types=%s",
            symbol, direction_label, strength, contributing_types,
        )


def _extract_signal_brief(result: SignalResult) -> dict[str, Any]:
    """提取单个信号的关键展示数据，用于共振信号的 contributing 字段。

    返回 {type, direction, metric} 三元组：
    - type: 信号类型（如 rsi_extreme）
    - direction: long/short
    - metric: 该信号最关键的展示数据（如 RSI 超买 73.2、TWAP偏离+2.07%）
    """
    rv = result.raw_values
    st = result.signal_type
    direction = result.direction

    if st == IntradaySignalType.VWAP_BREAKTHROUGH:
        cross = rv.get("cross", "")
        dev = rv.get("deviation_pct", 0)
        action = "上穿" if cross == "up" else "下穿"
        metric = f"{action}VWAP 偏离{dev:+.2f}%"
    elif st == IntradaySignalType.TWAP_DEVIATION:
        dev = rv.get("deviation_pct", 0)
        zone = "超买区" if dev > 0 else "超卖区"
        metric = f"偏离TWAP {dev:+.2f}% {zone}"
    elif st == IntradaySignalType.MACD_CROSS:
        cross = rv.get("cross", "")
        action = "金叉" if cross == "golden" else "死叉"
        metric = f"MACD{action}"
    elif st == IntradaySignalType.RSI_EXTREME:
        rsi = rv.get("rsi", 0)
        if direction == Direction.SHORT:
            metric = f"RSI超买 RSI={rsi:.1f}"
        else:
            metric = f"RSI超卖 RSI={rsi:.1f}"
    elif st == IntradaySignalType.VOLUME_PRICE_DIVERGENCE:
        div = rv.get("divergence", "")
        action = "顶背离" if div == "top" else "底背离"
        metric = f"量价{action}"
    else:
        metric = st

    return {
        "type": st,
        "direction": direction,
        "metric": metric,
    }
