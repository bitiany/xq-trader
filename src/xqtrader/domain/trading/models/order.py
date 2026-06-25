"""执行流模型 — 预订单 → 订单 → 事件 → 成交"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase, Base

from ..enums import (
    ApprovalStatus,
    OrderSide,
    OrderStatus,
    OrderType,
    PreOrderSide,
    PreOrderStatus,
)


class PreOrder(AuditedBase):
    """预订单 — 决策流与执行流的交接契约"""

    __bind_key__ = "trading"
    __tablename__ = "td_pre_order"

    instance_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True, comment="策略实例ID",
    )
    workflow_run_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="决策流 Run ID",
    )
    signal_date: Mapped[date] = mapped_column(Date, nullable=False, comment="信号日 T")
    execution_date: Mapped[date] = mapped_column(Date, nullable=False, comment="执行日 T+1")
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, comment="证券代码")
    side: Mapped[str] = mapped_column(
        String(8), nullable=False, default=PreOrderSide.OPEN,
        comment="方向: open/add/reduce/close",
    )
    target_weight: Mapped[float | None] = mapped_column(Float, nullable=True, comment="目标权重")
    current_weight: Mapped[float | None] = mapped_column(Float, nullable=True, comment="当前权重")
    target_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="目标数量")
    order_type: Mapped[str] = mapped_column(
        String(8), nullable=False, default=OrderType.LIMIT,
        comment="订单类型: limit/market",
    )
    limit_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4), nullable=True, comment="限价",
    )
    sizing_strategy: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="配仓策略ID",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PreOrderStatus.PENDING_APPROVAL,
        comment="状态机",
    )
    risk_check_passed: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="风控预检通过",
    )
    risk_check_detail: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default={}, comment="风控检查详情",
    )
    approval_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ApprovalStatus.PENDING,
        comment="审批状态: pending/approved/rejected/expired",
    )
    approved_by: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="审批人",
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="审批时间",
    )
    approval_comment: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="审批意见",
    )
    expired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="过期时间",
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True, comment="幂等键(instance_id:signal_date:symbol)",
    )
    node_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="工作流节点ID",
    )

    __table_args__ = ({"comment": "预订单(交接契约)"},)


class Order(AuditedBase):
    """订单 — OMS 核心实体，状态机驱动"""

    __bind_key__ = "trading"
    __tablename__ = "td_order"

    account_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True, comment="账户ID",
    )
    platform_order_id: Mapped[UUID | None] = mapped_column(
        unique=True, nullable=True, default=None, comment="平台内部订单ID",
    )
    instance_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True, comment="策略实例ID",
    )
    pre_order_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True, comment="预订单ID",
    )
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, comment="证券代码")
    side: Mapped[str] = mapped_column(
        String(8), nullable=False, default=OrderSide.BUY,
        comment="买卖方向: buy/sell",
    )
    order_type: Mapped[str] = mapped_column(
        String(8), nullable=False, default=OrderType.LIMIT,
        comment="订单类型: limit/market",
    )
    order_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4), nullable=True, comment="委托价格",
    )
    order_qty: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="委托数量",
    )
    filled_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4), nullable=True, comment="成交均价",
    )
    filled_qty: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="成交数量",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OrderStatus.CREATED,
        comment="OMS状态机",
    )
    broker_order_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="券商委托号",
    )
    reject_reason: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="拒绝原因",
    )
    signal_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="信号日")
    execution_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="执行日")
    workflow_run_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="执行流 Run ID",
    )

    __table_args__ = ({"comment": "订单"},)


class OrderEvent(Base):
    """订单事件溯源 — append-only，记录订单状态变更"""

    __bind_key__ = "trading"
    __tablename__ = "td_order_event"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="PK",
    )
    order_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True, comment="订单ID",
    )
    event_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="事件类型: created/risk_checked/submitted/"
        "partial_filled/filled/cancelled/rejected/expired",
    )
    event_data: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default={}, comment="事件详情",
    )
    operator: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="操作人(系统/人工)",
    )

    __table_args__ = ({"comment": "订单事件溯源"},)


class Trade(Base):
    """成交记录 — append-only，来自券商回报"""

    __bind_key__ = "trading"
    __tablename__ = "td_trade"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="PK",
    )
    order_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True, comment="订单ID",
    )
    account_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True, comment="账户ID",
    )
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, comment="证券代码")
    side: Mapped[str] = mapped_column(
        String(8), nullable=False, comment="买卖方向: buy/sell",
    )
    filled_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, comment="成交价格",
    )
    filled_qty: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="成交数量",
    )
    filled_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), nullable=True, comment="成交金额",
    )
    commission: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4), nullable=True, default=Decimal("0"), comment="手续费",
    )
    tax: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4), nullable=True, default=Decimal("0"), comment="印花税",
    )
    trade_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="成交时间",
    )
    broker_trade_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="券商成交号",
    )

    __table_args__ = ({"comment": "成交记录"},)
