"""预订单执行工作流服务 — 核心协调层。

职责单一：仅负责预订单 → OMS 订单创建、订单状态变更、QMT 提交；
其他职责已抽离至独立服务：
- 模拟撮合：SimulatedMatchingService（PAPER 账户本地撮合）
- 序列化：TradingSerializer（ORM → dict 转换）
- 类型转换/量化：OrderTypeConverter（QMT 委托类型、Decimal 量化）
- 校验：TradingValidator（预订单可下单性、滑点配置）
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from framework.commons.exceptions import BusinessException, WorkflowConfigError
from framework.commons.logger import get_logger
from framework.dal.transaction.transactional import transactional
from xqtrader.broker.services.qmt_trader import QmtTrader
from xqtrader.domain.trading.enums import (
    OrderEventType,
    OrderSide,
    OrderStatus,
    OrderType,
    PreOrderStatus,
)
from xqtrader.domain.trading.models.account import TradingAccount
from xqtrader.domain.trading.models.instance import StrategyInstance
from xqtrader.domain.trading.models.order import Order, OrderEvent, PreOrder
from xqtrader.domain.trading.workflow.order_type_converter import OrderTypeConverter
from xqtrader.domain.trading.workflow.trading_serializer import TradingSerializer
from xqtrader.domain.trading.workflow.trading_validator import TradingValidator

logger = get_logger(__name__)


class PreOrderExecutionWorkflowService:
    """预订单执行服务：预订单 → OMS 订单 → 实盘 QMT 提交（核心协调层）。"""

    _qmt_trader: QmtTrader | None = None

    @property
    def qmt_trader(self) -> QmtTrader:
        # 访问类属性（非实例属性），确保所有实例共享同一 QmtTrader，
        # 避免 execution_tools 每次新建 service 时重复创建 QmtTrader 连接。
        cls = type(self)
        if cls._qmt_trader is None:
            cls._qmt_trader = QmtTrader()
        return cls._qmt_trader

    async def load_execution_context(self, pre_order_id: int) -> dict[str, Any]:
        pre_order = await PreOrder.get(pre_order_id)
        if pre_order is None:
            raise WorkflowConfigError(f"PreOrder not found: {pre_order_id}")
        instance = await StrategyInstance.get(pre_order.instance_id)
        if instance is None:
            raise WorkflowConfigError(f"StrategyInstance not found: {pre_order.instance_id}")
        account = await TradingAccount.get(instance.account_id)
        if account is None:
            raise WorkflowConfigError(f"TradingAccount not found: {instance.account_id}")
        TradingValidator.validate_pre_order(pre_order, account)
        return {
            "pre_order_id": pre_order.id,
            "instance_id": instance.id,
            "account_id": account.id,
            "account_type": account.account_type,
            "broker_type": account.broker_type,
            "pre_order": TradingSerializer.serialize_pre_order(pre_order),
            "instance": TradingSerializer.serialize_instance(instance),
            "account": TradingSerializer.serialize_account(account),
            "submitter": OrderTypeConverter.resolve_submitter(account),
        }

    @transactional(bind_key="trading")
    async def create_order_from_pre_order(
        self,
        context: dict[str, Any],
        workflow_run_id: str,
        operator: str,
    ) -> dict[str, Any]:
        pre_order_id = int(context["pre_order_id"])
        pre_order = await PreOrder.get(pre_order_id)
        if pre_order is None:
            raise WorkflowConfigError(f"PreOrder not found: {pre_order_id}")
        account = await TradingAccount.get(int(context["account_id"]))
        if account is None:
            raise WorkflowConfigError(f"TradingAccount not found: {context['account_id']}")
        TradingValidator.validate_pre_order(pre_order, account)
        active_orders = await Order.filter(
            pre_order_id=pre_order_id,
            status__in=[
                OrderStatus.CREATED,
                OrderStatus.RISK_CHECKED,
                OrderStatus.SUBMITTED,
                OrderStatus.PARTIAL_FILLED,
                OrderStatus.FILLED,
            ],
            limit=1,
        )
        if active_orders:
            raise BusinessException(message=f"预订单已生成有效订单: {pre_order_id}")
        order = await Order.create(
            account_id=int(context["account_id"]),
            platform_order_id=uuid4(),
            instance_id=int(context["instance_id"]),
            pre_order_id=pre_order.id,
            symbol=pre_order.symbol,
            side=OrderTypeConverter.to_order_side(pre_order.side),
            order_type=pre_order.order_type,
            order_price=pre_order.limit_price if pre_order.order_type == OrderType.LIMIT else None,
            order_qty=int(pre_order.target_qty or 0),
            filled_price=None,
            filled_qty=0,
            status=OrderStatus.CREATED,
            broker_order_id=None,
            reject_reason=None,
            signal_date=pre_order.signal_date,
            execution_date=pre_order.execution_date,
            workflow_run_id=workflow_run_id,
        )
        await self.append_event(
            order.id,
            OrderEventType.CREATED,
            {"pre_order_id": pre_order.id, "workflow_run_id": workflow_run_id},
            operator,
        )
        await self.append_event(
            order.id,
            OrderEventType.RISK_CHECKED,
            {"risk_check_detail": pre_order.risk_check_detail or {}},
            operator,
        )
        return OrderTypeConverter.build_order_result(order, context)

    async def submit_qmt_order(
        self,
        order_id: int,
        operator: str,
    ) -> dict[str, Any]:
        order = await self.get_order_for_submit(order_id)
        try:
            broker_order_id = await self.qmt_trader.order_stock(
                stock_code=order.symbol,
                order_type=OrderTypeConverter.to_qmt_order_type(order.side),
                order_volume=order.order_qty,
                price_type=OrderTypeConverter.to_qmt_price_type(order.order_type),
                price=OrderTypeConverter.to_qmt_price(order.order_price, order.order_type),
                strategy_name="xqtrader_pre_order_execution",
                order_remark=f"pre_order_id={order.pre_order_id};order_id={order.id}",
            )
        except Exception as exc:
            await self.mark_order_rejected(order_id, str(exc), operator)
            raise
        # 补偿机制：broker 已下单后 mark_qmt_order_submitted 失败时，必须撤销 broker 订单，
        # 否则会产生僵尸订单（broker 端有订单但本地无 broker_order_id，回调被静默丢弃）。
        try:
            await self.mark_qmt_order_submitted(order_id, str(broker_order_id), operator)
        except Exception:
            logger.error(
                "submit_qmt_order: mark_qmt_order_submitted 失败，尝试撤销 broker 订单 "
                "order_id=%s broker_order_id=%s",
                order_id, broker_order_id,
                exc_info=True,
            )
            try:
                await self.qmt_trader.cancel_order(int(broker_order_id))
                logger.info(
                    "submit_qmt_order: broker 订单已撤销 order_id=%s broker_order_id=%s",
                    order_id, broker_order_id,
                )
            except Exception:
                logger.error(
                    "submit_qmt_order: 撤销 broker 订单失败（需人工对账）"
                    "order_id=%s broker_order_id=%s",
                    order_id, broker_order_id,
                    exc_info=True,
                )
            # 标记本地订单为 REJECTED，与 broker 端状态对齐
            try:
                await self.mark_order_rejected(
                    order_id,
                    f"mark_qmt_order_submitted 失败，broker 订单已尝试撤销: {broker_order_id}",
                    operator,
                )
            except Exception:
                logger.error(
                    "submit_qmt_order: 标记 REJECTED 失败 order_id=%s",
                    order_id,
                    exc_info=True,
                )
            raise
        refreshed = await Order.get(order_id)
        if refreshed is None:
            raise WorkflowConfigError(f"Order not found after qmt submit: {order_id}")
        return {
            "order": TradingSerializer.serialize_order(refreshed),
            "submitter": "qmt",
            "broker_order_id": str(broker_order_id),
        }

    @transactional(bind_key="trading")
    async def mark_qmt_order_submitted(
        self,
        order_id: int,
        broker_order_id: str,
        operator: str,
    ) -> None:
        order = await self.get_order_for_submit(order_id)
        await self.mark_submitted(
            order=order,
            broker_order_id=broker_order_id,
            event_data={"submitter": "qmt", "broker_order_id": broker_order_id},
            operator=operator,
        )

    @transactional(bind_key="trading")
    async def mark_order_rejected(self, order_id: int, reason: str, operator: str) -> None:
        order = await Order.get(order_id)
        if order is None:
            raise WorkflowConfigError(f"Order not found: {order_id}")
        await order.update({"status": OrderStatus.REJECTED, "reject_reason": reason[:256]})
        if order.pre_order_id is not None:
            pre_order = await PreOrder.get(order.pre_order_id)
            if pre_order is not None and pre_order.status == PreOrderStatus.SUBMITTED:
                # 订单被拒绝后，预订单回退到 APPROVED，允许操作员排查后重新提交
                await pre_order.update({"status": PreOrderStatus.APPROVED})
        await self.append_event(
            order.id,
            OrderEventType.REJECTED,
            {"reason": reason},
            operator,
        )

    async def get_order_for_submit(self, order_id: int) -> Order:
        order = await Order.get(order_id)
        if order is None:
            raise WorkflowConfigError(f"Order not found: {order_id}")
        if order.status != OrderStatus.CREATED:
            raise BusinessException(message=f"订单状态为 {order.status}，不可提交")
        if order.order_qty <= 0:
            raise BusinessException(message=f"订单数量必须大于0: {order.order_qty}")
        # reduce_only 安全校验（CRITICAL）：
        # Kill Switch 触发后设置 account.reduce_only=True，禁止该账户任何 BUY 订单提交。
        # 没有此校验时，Kill Switch 之前已创建的 CREATED BUY 订单仍可被 submit 成交，
        # 直接违反 reduce_only 核心安全语义。SELL 方向（含 Kill Switch close 订单）不受限。
        if order.account_id is None:
            raise WorkflowConfigError(f"订单缺少账户ID: {order.id}")
        account = await TradingAccount.get(order.account_id)
        if account is None:
            raise WorkflowConfigError(f"TradingAccount not found: {order.account_id}")
        if account.reduce_only and order.side == OrderSide.BUY:
            raise BusinessException(
                message=(
                    f"账户处于仅减仓状态(reduce_only=True)，禁止提交买入订单: "
                    f"account={account.id}, order={order.id}"
                ),
            )
        return order

    async def mark_submitted(
        self,
        order: Order,
        broker_order_id: str,
        event_data: dict[str, Any],
        operator: str,
    ) -> None:
        await order.update({"status": OrderStatus.SUBMITTED, "broker_order_id": broker_order_id})
        if order.pre_order_id is not None:
            pre_order = await PreOrder.get(order.pre_order_id)
            if pre_order is not None:
                await pre_order.update({"status": PreOrderStatus.SUBMITTED})
        await self.append_event(order.id, OrderEventType.SUBMITTED, event_data, operator)

    @staticmethod
    async def append_event(
        order_id: int,
        event_type: str,
        event_data: dict[str, Any],
        operator: str,
    ) -> None:
        await OrderEvent.create(
            order_id=order_id,
            event_type=event_type,
            event_data=event_data,
            operator=operator,
        )
