"""持仓快照"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base


class PositionSnapshot(Base):
    """持仓快照 — 按账户+标的+日期记录持仓状态"""

    __bind_key__ = "trading"
    __tablename__ = "td_position_snapshot"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="PK",
    )
    account_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True, comment="账户ID",
    )
    instance_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True, comment="策略实例ID")
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, comment="证券代码")
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, comment="快照日期")
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="持仓数量")
    available_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="可用数量(T+1)")
    cost_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True, comment="成本价")
    market_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True, comment="最新价")
    market_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True, comment="市值")
    weight: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True, comment="权重")
    target_weight: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True, comment="目标权重")
    weight_deviation: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True, comment="权重偏离")
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True, comment="浮动盈亏")
    daily_pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True, comment="当日盈亏")
    snapshot_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="快照时间戳")
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default={}, comment="扩展信息")

    __table_args__ = ({"comment": "持仓快照"},)
