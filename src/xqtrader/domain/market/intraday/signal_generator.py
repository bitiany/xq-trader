"""盘中信号生成器 - 消费异动事件 -> 自动创建 PreOrder -> 提交执行工作流

职责：
1. 监听 Redis `intraday:tick_anomaly` 频道
2. 当异动满足信号阈值时（如涨幅 > surge_threshold），生成交易信号
3. 创建 auto-approved PreOrder（参考 kill_switch 模式）
4. 调用 execute_workflow 提交到执行工作流（模拟盘走 SimulatedMatchingService）

信号策略（V1 简单版）：
- surge 且 change_pct > +surge_threshold% -> BUY（开仓）
- surge 且 change_pct < -surge_threshold% -> SELL（平仓，如果有持仓）
- volume_spike -> 仅记录，不触发交易（需配合其他信号确认）

去重：同一 symbol 在同一交易日内只产生一次信号（idempotency_key 含日期+symbol）
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from framework.commons.redis_client import redis_client
from framework.commons.time_util import now_shanghai, today_shanghai
from xqtrader.domain.market.intraday.publishers import CHANNEL_TICK_ANOMALY
from xqtrader.domain.trading.enums import (
    ApprovalStatus,
    OrderType,
    PreOrderSide,
    PreOrderStatus,
)
from xqtrader.domain.trading.models.order import PreOrder
from xqtrader.domain.workflow.dispatch import execute_workflow

logger = logging.getLogger("INTRADAY.SIGNAL")

# 默认信号阈值
_SURGE_THRESHOLD_PCT = 5.0  # 涨跌幅超过 5% 触发信号
# 默认下单数量（股）
_DEFAULT_ORDER_QTY = 100


class IntradaySignalGenerator:
    """盘中信号生成器 - 异动事件 -> PreOrder -> 执行工作流

    通过 Redis Pub/Sub 订阅异动事件，在异动满足条件时自动创建并提交预订单。
    线程模型：在 asyncio 事件循环中运行，通过 run_in_executor 执行阻塞式 pubsub.listen()。
    """

    _instance: IntradaySignalGenerator | None = None

    @classmethod
    def get_instance(cls) -> IntradaySignalGenerator:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._instance_id: int = 1  # 默认模拟盘策略实例
        self._surge_threshold: float = _SURGE_THRESHOLD_PCT
        self._order_qty: int = _DEFAULT_ORDER_QTY
        self._running: bool = False
        self._task: asyncio.Task[None] | None = None
        self._triggered_symbols: set[str] = set()  # 当日已触发 symbol 去重

    @property
    def is_running(self) -> bool:
        return self._running

    def configure(
        self,
        instance_id: int = 1,
        surge_threshold: float = _SURGE_THRESHOLD_PCT,
        order_qty: int = _DEFAULT_ORDER_QTY,
    ) -> None:
        """配置信号生成器参数"""
        self._instance_id = instance_id
        self._surge_threshold = surge_threshold
        self._order_qty = order_qty

    async def start(self) -> None:
        """启动信号生成器"""
        if self._running:
            logger.warning("信号生成器已在运行")
            return
        self._running = True
        self._triggered_symbols.clear()
        self._task = asyncio.create_task(self._listen_anomalies())
        logger.info(
            "盘中信号生成器已启动: instance_id=%d, surge_threshold=%.1f%%",
            self._instance_id, self._surge_threshold,
        )

    async def stop(self) -> None:
        """停止信号生成器"""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("盘中信号生成器已停止")

    async def _listen_anomalies(self) -> None:
        """监听异动事件

        使用 loop.run_in_executor 在线程中运行阻塞式 pubsub.listen()，
        通过 asyncio.Queue + run_coroutine_threadsafe 桥接到事件循环处理消息。
        """
        pubsub = redis_client.pubsub()
        pubsub.subscribe(CHANNEL_TICK_ANOMALY)
        logger.info("已订阅异动事件频道: %s", CHANNEL_TICK_ANOMALY)

        loop = asyncio.get_running_loop()
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
            except Exception:
                logger.error("异动事件 PubSub 监听线程异常", exc_info=True)

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
                        await self._handle_anomaly(data)
                except asyncio.TimeoutError:
                    continue
        finally:
            pubsub.unsubscribe(CHANNEL_TICK_ANOMALY)
            pubsub.close()
            listener_future.cancel()

    async def _handle_anomaly(self, data: dict[str, Any]) -> None:
        """处理异动事件 -> 生成信号 -> 创建 PreOrder -> 提交执行"""
        symbol = data.get("symbol", "")
        anomaly_type = data.get("anomaly_type", "")
        detail = data.get("detail", {})

        if not symbol:
            return

        # 当日去重
        if symbol in self._triggered_symbols:
            logger.debug("symbol=%s 当日已触发过信号，跳过", symbol)
            return

        change_pct = detail.get("change_pct")
        if change_pct is None:
            return

        # 信号判断
        if anomaly_type == "surge":
            if change_pct > self._surge_threshold:
                side = PreOrderSide.OPEN
                logger.info(
                    "盘中信号触发: symbol=%s, surge=+%.2f%%, side=BUY",
                    symbol, change_pct,
                )
            elif change_pct < -self._surge_threshold:
                side = PreOrderSide.CLOSE
                logger.info(
                    "盘中信号触发: symbol=%s, surge=%.2f%%, side=SELL",
                    symbol, change_pct,
                )
            else:
                return
        else:
            # volume_spike 等其他异动暂不触发交易
            return

        # 创建并提交 PreOrder
        try:
            await self._create_and_submit_preorder(symbol, side, change_pct)
            self._triggered_symbols.add(symbol)
        except Exception:
            logger.error(
                "盘中信号执行失败: symbol=%s, side=%s",
                symbol, side, exc_info=True,
            )

    async def _create_and_submit_preorder(
        self,
        symbol: str,
        side: str,
        change_pct: float,
    ) -> None:
        """创建 auto-approved PreOrder 并提交执行工作流"""
        today = today_shanghai()
        now = now_shanghai()
        workflow_run_id = f"intraday_signal:{today.isoformat()}:{symbol}"
        idempotency_key = f"intraday:{today.isoformat()}:{symbol}"

        # 参考 kill_switch 模式：直接创建 APPROVED 状态的 PreOrder
        pre_order = await PreOrder.create(
            instance_id=self._instance_id,
            workflow_run_id=workflow_run_id,
            signal_date=today,
            execution_date=today,
            symbol=symbol,
            side=side,
            target_weight=None,
            current_weight=None,
            target_qty=self._order_qty,
            order_type=OrderType.MARKET,
            limit_price=None,
            sizing_strategy="intraday_surge",
            status=PreOrderStatus.APPROVED,
            risk_check_passed=True,
            risk_check_detail={
                "source": "intraday_signal",
                "anomaly_type": "surge",
                "change_pct": change_pct,
            },
            approval_status=ApprovalStatus.APPROVED,
            approved_by="intraday_signal_generator",
            approved_at=now,
            approval_comment=f"盘中异动信号自动审批: change_pct={change_pct:.2f}%",
            idempotency_key=idempotency_key,
            node_id="intraday_signal_generator",
        )

        logger.info(
            "PreOrder 已创建: id=%s, symbol=%s, side=%s, qty=%d",
            pre_order.id, symbol, side, self._order_qty,
        )

        # 提交执行工作流
        result = await execute_workflow(
            flow_id="pre_order_execution_flow",
            inputs={
                "pre_order_id": pre_order.id,
                "operator": "intraday_signal_generator",
            },
            workspace_id=f"intraday_signal:{pre_order.id}",
        )

        outputs = result.get("outputs") or {}
        submit_result = outputs.get("submit_simulated_order") or outputs.get("submit_qmt_order") or {}
        create_result = outputs.get("create_order") or {}
        order = submit_result.get("order") or create_result.get("order")

        if order:
            logger.info(
                "执行工作流完成: pre_order_id=%s, order_id=%s, status=%s",
                pre_order.id,
                order.get("id"),
                order.get("status"),
            )
        else:
            logger.warning(
                "执行工作流完成但无订单信息: pre_order_id=%s, result=%s",
                pre_order.id,
                json.dumps(result, ensure_ascii=False, default=str)[:500],
            )
