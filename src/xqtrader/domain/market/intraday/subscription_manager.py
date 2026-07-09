"""盘内 QMT 订阅管理器 - 封装分钟线与全推快照的订阅/回调/取消订阅

从 IntradayMonitorTask 拆分而来，职责单一：
- 管理 QMT 分钟线订阅与回调桥接
- 管理 QMT 全推快照订阅与异动扫描桥接
- 取消订阅的生命周期管理

线程模型：
- QMT 回调在内部线程中执行
- MinuteBarCollector 通过 threading.Lock 保证线程安全，可直接调用
- publish_* 函数是线程安全的 Redis 操作，可直接调用
"""

from __future__ import annotations

from typing import Any

from framework.commons.logger import get_logger
from xqtrader.broker.services.qmt_data_collector import (
    QmtDataCollector,
    convert_symbol_from_qmt,
)
from xqtrader.domain.market.intraday.minute_bar_collector import MinuteBarCollector
from xqtrader.domain.market.intraday.publishers import (
    publish_minute_bar_ready,
    publish_tick_anomaly,
)
from xqtrader.domain.market.intraday.tick_anomaly_scanner import TickAnomalyScanner

logger = get_logger("INTRADAY.SUBSCRIPTION")


class IntradaySubscriptionManager:
    """盘内 QMT 订阅管理器

    封装分钟线与全推快照的订阅、回调、取消订阅，从 IntradayMonitorTask 拆分。
    回调在 QMT 内部线程中执行，通过 threading.Lock 与 Redis Pub/Sub 保证线程安全。
    """

    def __init__(
        self,
        qmt: QmtDataCollector,
        collector: MinuteBarCollector,
        scanner: TickAnomalyScanner,
    ) -> None:
        self._qmt = qmt
        self._collector = collector
        self._scanner = scanner
        self._scanner.set_callback(self._on_anomaly_detected)
        self._minute_bar_seq: int | None = None
        self._whole_quote_seq: int | None = None

    def start_subscriptions(self, symbols: list[str]) -> None:
        """启动 QMT 分钟线与全推快照订阅

        Args:
            symbols: 证券代码列表（Tushare 格式）
        """
        # 1. 订阅分钟线
        self._minute_bar_seq = self._qmt.subscribe_minute_bar(
            stock_codes=symbols,
            callback=self._on_bar_received,
            period="1m",
        )

        # 2. 订阅全推快照（失败不阻塞分钟线监控）
        try:
            self._whole_quote_seq = self._subscribe_whole_quote(symbols)
        except Exception as e:
            logger.error("订阅 QMT 全推快照失败: %s", e, exc_info=True)

    def stop_subscriptions(self) -> None:
        """取消所有 QMT 订阅"""
        if self._minute_bar_seq is not None:
            try:
                self._qmt.unsubscribe(self._minute_bar_seq)
            except Exception as e:
                logger.warning("取消分钟线订阅失败: seq=%s, error=%s", self._minute_bar_seq, e)
            self._minute_bar_seq = None

        if self._whole_quote_seq is not None:
            try:
                self._qmt.unsubscribe(self._whole_quote_seq)
            except Exception as e:
                logger.warning("取消全推快照订阅失败: seq=%s, error=%s", self._whole_quote_seq, e)
            self._whole_quote_seq = None

    def _subscribe_whole_quote(self, symbols: list[str]) -> int:
        """订阅 QMT 全推快照（异动扫描）"""
        def _on_whole_quote(datas: dict[str, dict[str, Any]]) -> None:
            """xtdata 回调：{qmt_symbol: {lastPrice, volume, amount, ...}}"""
            self._scanner.on_quote_callback(datas)

        return self._qmt.subscribe_whole_quote(symbols, _on_whole_quote)

    # ── QMT 回调（在 QMT 内部线程中执行）────────────────────

    def _on_bar_received(self, stock_code: str, bar_data: dict[str, Any]) -> None:
        """QMT 分钟线回调

        MinuteBarCollector.on_bar_callback 通过 threading.Lock 保证线程安全，可直接调用。
        """
        self._collector.on_bar_callback(stock_code, bar_data)

        # 发布分钟线就绪事件（Redis Pub/Sub，线程安全）
        try:
            symbol = convert_symbol_from_qmt(stock_code)
            trade_time = bar_data.get("time", "")
            publish_minute_bar_ready(symbol, str(trade_time), {
                "open": bar_data.get("open"),
                "high": bar_data.get("high"),
                "low": bar_data.get("low"),
                "close": bar_data.get("close"),
                "volume": bar_data.get("volume"),
                "amount": bar_data.get("amount"),
            })
        except Exception as e:
            logger.error("发布分钟线就绪事件失败: %s, error=%s", stock_code, e, exc_info=True)

    def _on_anomaly_detected(self, symbol: str, anomaly_type: str, detail: dict[str, Any]) -> None:
        """Scanner 异动回调（在 QMT 内部线程中执行）"""
        try:
            publish_tick_anomaly(symbol, anomaly_type, detail)
        except Exception as e:
            logger.error("发布异动事件失败: symbol=%s, type=%s, error=%s",
                         symbol, anomaly_type, e, exc_info=True)
