"""信号值表 — fac_signal_value。

存储非截面信号（缠论买卖点、K线形态识别等离散/布尔/枚举信号）。
"""

from datetime import date

from sqlalchemy import Date, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base


class FacSignalValue(Base):
    """信号值表（每日每股每信号一行）。"""

    __bind_key__ = "stock"
    __tablename__ = "fac_signal_value"

    symbol: Mapped[str] = mapped_column(
        String(10), primary_key=True, nullable=False, comment="证券代码"
    )
    trade_date: Mapped[date] = mapped_column(
        Date, primary_key=True, nullable=False, comment="交易日期"
    )
    signal_id: Mapped[str] = mapped_column(
        String(32), primary_key=True, nullable=False, comment="信号标识"
    )
    signal_value: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="信号值(离散: 1=买, -1=卖, 0=无)"
    )
    signal_strength: Mapped[float] = mapped_column(
        Float, nullable=True, comment="信号强度(0~1)"
    )
    signal_context: Mapped[str] = mapped_column(
        String(256), nullable=True, default="",
        comment="信号上下文(JSON: 级别/类型/触发条件等)",
    )

    __table_args__ = (
        Index("ix_fac_sv_date_signal", "trade_date", "signal_id"),
        Index("ix_fac_sv_symbol_date", "symbol", "trade_date"),
        {"comment": "信号值表 — 缠论/K线形态等非截面离散信号"},
    )
