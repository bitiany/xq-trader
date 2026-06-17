"""策略实例 & 模拟盘会话"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase

from ..enums import InstanceStatus, PaperSessionStatus, RunMode


class StrategyInstance(AuditedBase):
    """策略实例 — 核心枢纽，关联账户与策略定义，承载运行时配置"""

    __bind_key__ = "trading"
    __tablename__ = "td_strategy_instance"

    account_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True, comment="交易账户ID",
    )
    strategy_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True, comment="策略定义ID",
    )
    instance_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="实例名称")
    run_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RunMode.LIVE_MANUAL,
        comment="运行模式: live_manual/live_auto/paper/backtest",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=InstanceStatus.DRAFT,
        comment="状态: draft/running/paused/stopped",
    )
    config: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default={}, comment="策略运行时配置",
    )
    position_sizing: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default={}, comment="仓位管理配置",
    )
    risk_overrides: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default={}, comment="风控规则覆盖",
    )
    universe_pool: Mapped[str | None] = mapped_column(
        String(32), nullable=True, default="", comment="样本池",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="启动时间",
    )
    stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="停止时间",
    )
    description: Mapped[str | None] = mapped_column(
        String(256), nullable=True, default="", comment="说明",
    )

    __table_args__ = ({"comment": "策略实例"},)


class PaperSession(AuditedBase):
    """模拟盘会话 — 记录模拟盘运行周期"""

    __bind_key__ = "trading"
    __tablename__ = "td_paper_session"

    instance_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True, comment="策略实例ID",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PaperSessionStatus.ACTIVE,
        comment="状态: active/completed/abandoned",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="开始时间",
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="结束时间",
    )
    initial_capital: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4), nullable=True, default=None, comment="初始资金",
    )
    result_summary: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default={}, comment="会话结果摘要",
    )
    promote_to_live: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否已转实盘",
    )

    __table_args__ = ({"comment": "模拟盘会话"},)
