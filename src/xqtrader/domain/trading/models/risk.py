"""风控规则 & 风控事件"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase, Base

from ..enums import RiskCategory, RiskLevel, RiskScope


class RiskRule(AuditedBase):
    """风控规则 — 事前/事中/事后风控规则定义"""

    __bind_key__ = "trading"
    __tablename__ = "td_risk_rule"

    rule_code: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, comment="规则编码",
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="规则名称")
    category: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RiskCategory.POSITION,
        comment="类别: position/capital/timing/circuit_breaker",
    )
    level: Mapped[str] = mapped_column(
        String(10), nullable=False, default=RiskLevel.WARN,
        comment="级别: info/warn/critical/fatal",
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="是否启用",
    )
    params: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default={}, comment="规则参数",
    )
    scope: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RiskScope.GLOBAL,
        comment="作用域: global/account/instance",
    )
    scope_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="作用域ID(account_id/instance_id)",
    )
    description: Mapped[str | None] = mapped_column(
        String(256), nullable=True, default="", comment="规则说明",
    )

    __table_args__ = ({"comment": "风控规则"},)


class RiskEvent(Base):
    """风控事件 — append-only，记录风控触发与处理"""

    __bind_key__ = "trading"
    __tablename__ = "td_risk_event"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="PK",
    )
    rule_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True, comment="风控规则ID",
    )
    account_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True, comment="账户ID",
    )
    instance_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True, comment="策略实例ID",
    )
    event_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="事件类型: blocked/warning/circuit_breaker/kill_switch",
    )
    level: Mapped[str] = mapped_column(
        String(10), nullable=False, default=RiskLevel.WARN,
        comment="级别: info/warn/critical/fatal",
    )
    detail: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default={}, comment="事件详情",
    )
    action_taken: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="采取的措施",
    )
    resolved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否已处理",
    )
    resolved_by: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="处理人",
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="处理时间",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.now,
        comment="事件时间",
    )

    __table_args__ = ({"comment": "风控事件"},)
