"""新因子值窄表 — fac_factor_value。

与旧表 sdc_factor_value 隔离，新增 pool_id 维度。
单因子 pool_id 固定为 'all'，Alpha 因子按样本池分别写入。
"""

from datetime import date

from sqlalchemy import Date, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base
from framework.dal.timescale import timescale


@timescale(
    time_column="trade_date",
    chunk_interval="6 month",
    compress_after="6 months",
    compress_segmentby="symbol",
)
class FacFactorValue(Base):
    """新因子值窄表（每日每股每因子每样本池一行）。"""

    __bind_key__ = "stock"
    __tablename__ = "fac_factor_value"

    symbol: Mapped[str] = mapped_column(
        String(10), primary_key=True, nullable=False, comment="证券代码"
    )
    trade_date: Mapped[date] = mapped_column(
        Date, primary_key=True, nullable=False, comment="交易日期"
    )
    factor_id: Mapped[str] = mapped_column(
        String(32), primary_key=True, nullable=False, comment="因子标识"
    )
    pool_id: Mapped[str] = mapped_column(
        String(16), primary_key=True, nullable=False, default="all",
        comment="样本池标识, 单因子默认all, Alpha因子按池写入",
    )
    factor_value: Mapped[float] = mapped_column(
        Float, nullable=True, comment="因子值"
    )

    __table_args__ = (
        Index("ix_fac_fv_date_factor_pool", "trade_date", "factor_id", "pool_id"),
        Index("ix_fac_fv_symbol_date", "symbol", "trade_date"),
        Index("ix_fac_fv_date_pool", "trade_date", "pool_id"),
        {"comment": "新因子值窄表 — 每日每股每因子每样本池一行"},
    )
