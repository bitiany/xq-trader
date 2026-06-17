"""交易账户 & 资金快照"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase, Base

from ..enums import AccountType, BrokerType


class TradingAccount(AuditedBase):
    """交易账户 — 实盘/模拟盘账户信息"""

    __bind_key__ = "trading"
    __tablename__ = "td_account"

    account_code: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, comment="账户编码",
    )
    account_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="账户名称")
    account_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AccountType.LIVE,
        comment="账户类型: live/paper",
    )
    broker_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=BrokerType.QMT,
        comment="券商适配: qmt/simulated/backtest",
    )
    broker_config: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default={}, comment="券商连接配置",
    )
    initial_capital: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), comment="初始资金",
    )
    available_cash: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), comment="可用现金",
    )
    frozen_cash: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), comment="冻结现金",
    )
    reduce_only: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="仅减仓标记(kill switch)",
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否启用")
    description: Mapped[str | None] = mapped_column(
        String(256), nullable=True, default="", comment="说明",
    )

    __table_args__ = ({"comment": "交易账户"},)


class AccountSnapshot(Base):
    """资金快照 — 按账户+日期记录资金状态"""

    __bind_key__ = "trading"
    __tablename__ = "td_account_snapshot"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="PK",
    )
    account_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True, comment="账户ID",
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, comment="快照日期")
    total_assets: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), comment="总资产",
    )
    market_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), comment="持仓市值",
    )
    available_cash: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), comment="可用现金",
    )
    frozen_cash: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), comment="冻结现金",
    )
    daily_pnl: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), comment="当日盈亏",
    )
    cumulative_pnl: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), comment="累计盈亏",
    )
    daily_return: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), nullable=False, default=Decimal("0"), comment="当日收益率",
    )
    position_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="持仓标的数",
    )
    snapshot_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="快照时间戳",
    )

    __table_args__ = ({"comment": "资金快照"},)
