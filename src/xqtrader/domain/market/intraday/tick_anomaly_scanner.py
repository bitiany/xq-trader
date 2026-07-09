"""Tick 异动扫描器 - 订阅全推快照，内存检测量价异动，不落库

基于 QMT subscribe_whole_quote 的全推快照（3s 延迟），在内存中检测：
- 急涨急跌：1分钟内涨跌幅超阈值
- 量脉冲：成交量较前 N 分钟均量放大超阈值

命中异动的标的通过回调通知 IntradayMonitorTask，可选择加入动态股票池。
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from xqtrader.broker.services.qmt_data_collector import convert_symbol_from_qmt

logger = logging.getLogger("INTRADAY.ANOMALY")

# 异动检测阈值
_DEFAULT_SURGE_THRESHOLD = 0.03  # 1分钟内涨跌幅超 3%
_DEFAULT_VOLUME_RATIO = 2.0  # 成交量较前 5 分钟均量放大 2 倍
_SNAPSHOT_WINDOW = 60  # 快照保留窗口（秒），用于计算 1 分钟涨跌幅


class TickAnomalyScanner:
    """Tick 异动扫描器（内存，不落库）

    线程模型：
    - on_quote_callback 由 QMT 内部线程调用
    - 异动命中时通过 callback 通知主事件循环
    """

    def __init__(
        self,
        surge_threshold: float = _DEFAULT_SURGE_THRESHOLD,
        volume_ratio: float = _DEFAULT_VOLUME_RATIO,
    ) -> None:
        self._surge_threshold = surge_threshold
        self._volume_ratio = volume_ratio

        # 快照历史 {symbol: deque[(timestamp, last_price, volume)]}
        # 用于计算 1 分钟涨跌幅与量比
        self._history: dict[str, deque[tuple[float, float, int]]] = {}
        self._callback: Callable[[str, str, dict[str, Any]], None] | None = None
        self._running = False

    def set_callback(self, callback: Callable[[str, str, dict[str, Any]], None]) -> None:
        """设置异动回调

        回调签名：callback(symbol, anomaly_type, detail)
            symbol: 证券代码（Tushare 格式，如 600000.SH）
            anomaly_type: "surge" | "volume_spike"
            detail: 异动详情字典
        """
        self._callback = callback

    def on_quote_callback(self, datas: dict[str, dict[str, Any]]) -> None:
        """QMT subscribe_whole_quote 回调（在 QMT 内部线程中执行）

        Args:
            datas: {qmt_symbol: {lastPrice, volume, amount, ...}}
        """
        if not self._running:
            return

        now = time.time()

        for qmt_symbol, quote in datas.items():
            try:
                self._process_quote(qmt_symbol, quote, now)
            except Exception as e:
                logger.error("处理快照失败: %s, error=%s", qmt_symbol, e, exc_info=True)

    def start(self) -> None:
        """启动扫描"""
        if self._running:
            return
        self._running = True
        self._history.clear()
        logger.info(
            "TickAnomalyScanner 已启动: surge=%.2f%%, volume_ratio=%.1fx",
            self._surge_threshold * 100, self._volume_ratio,
        )

    def stop(self) -> None:
        """停止扫描"""
        self._running = False
        self._history.clear()
        logger.info("TickAnomalyScanner 已停止")

    def _process_quote(self, qmt_symbol: str, quote: dict[str, Any], now: float) -> None:
        """处理单个标的快照"""
        # 证券代码转换：SH.600000 -> 600000.SH（复用 qmt_data_collector 的转换函数）
        symbol = convert_symbol_from_qmt(qmt_symbol)
        if "." not in symbol:
            return

        last_price = float(quote.get("lastPrice", 0))
        volume = int(quote.get("volume", 0))
        amount = float(quote.get("amount", 0))

        if last_price <= 0:
            return

        # 获取或创建历史队列
        history = self._history.get(symbol)
        if history is None:
            history = deque(maxlen=_SNAPSHOT_WINDOW * 10)  # 保留足够样本
            self._history[symbol] = history

        # 检测急涨急跌：与 60 秒前的价格比较
        self._detect_surge(symbol, last_price, volume, amount, now, history)

        # 更新历史
        history.append((now, last_price, volume))

    def _detect_surge(
        self,
        symbol: str,
        price: float,
        volume: int,
        amount: float,
        now: float,
        history: deque[tuple[float, float, int]],
    ) -> None:
        """检测急涨急跌与量脉冲"""
        if not history:
            return

        # 找到 60 秒前的快照（用于计算 1 分钟涨跌幅）
        reference = None
        for ts, ref_price, ref_vol in history:
            if now - ts >= _SNAPSHOT_WINDOW:
                reference = (ts, ref_price, ref_vol)
            else:
                break

        if reference is None:
            return

        _, ref_price, ref_vol = reference
        if ref_price <= 0:
            return

        # 1 分钟涨跌幅
        change_ratio = (price - ref_price) / ref_price
        if abs(change_ratio) >= self._surge_threshold:
            self._notify(symbol, "surge", {
                "change_ratio": round(change_ratio, 4),
                "change_pct": round(change_ratio * 100, 2),
                "price": price,
                "ref_price": ref_price,
                "timestamp": now,
            })

        # 量脉冲：当前累计成交量较 1 分钟前增量 / 前 N 分钟均量增量
        # 注意：QMT volume 是当日累计成交量，需计算增量
        vol_delta = volume - ref_vol
        if vol_delta > 0:
            # 计算近 N 分钟的平均增量
            recent_deltas = []
            history_list = list(history)
            for i in range(1, len(history_list)):
                ts_prev, _, vol_prev = history_list[i - 1]
                ts_curr, _, vol_curr = history_list[i]
                if ts_curr - ts_prev > 0:
                    delta = vol_curr - vol_prev
                    if delta > 0:
                        recent_deltas.append(delta)

            if len(recent_deltas) >= 2:
                avg_delta = sum(recent_deltas) / len(recent_deltas)
                if avg_delta > 0 and vol_delta / avg_delta >= self._volume_ratio:
                    self._notify(symbol, "volume_spike", {
                        "volume_ratio": round(vol_delta / avg_delta, 2),
                        "volume_delta": vol_delta,
                        "avg_volume_delta": round(avg_delta, 0),
                        "price": price,
                        "timestamp": now,
                    })

    def _notify(self, symbol: str, anomaly_type: str, detail: dict[str, Any]) -> None:
        """通知异动事件"""
        if self._callback is None:
            return
        try:
            self._callback(symbol, anomaly_type, detail)
        except Exception as e:
            logger.error("异动回调失败: symbol=%s, type=%s, error=%s", symbol, anomaly_type, e, exc_info=True)
