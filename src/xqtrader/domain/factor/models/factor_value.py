"""逐标的因子值窄表 — 仅存储技术/量价/资金流等逐标的可独立计算的因子。

截面因子（估值指标、财务指标）不在此表存储，通过 CrossSectionReader 按需加载。
"""

from datetime import date

from sqlalchemy import Date, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base
from framework.dal.timescale import timescale


@timescale(
    time_column="trade_date",
    chunk_interval="6 month",
    compress_after="1 year",
    compress_segmentby="symbol",
)
class FacFactorValue(Base):
    """逐标的因子值窄表（TimescaleDB hypertable）。"""

    __bind_key__ = "stock"
    __tablename__ = "fac_factor_value"

    symbol: Mapped[str] = mapped_column(String(10), primary_key=True, nullable=False, comment="证券代码")
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True, nullable=False, comment="交易日期")
    factor_id: Mapped[str] = mapped_column(String(32), primary_key=True, nullable=False, comment="因子标识")
    pool_id: Mapped[str] = mapped_column(String(16), primary_key=True, nullable=False, comment="样本池标识，默认all")
    factor_value: Mapped[float | None] = mapped_column(Float, nullable=True, comment="因子值（去极值后）")

    __table_args__ = (
        {"comment": "逐标的因子值窄表 — 仅技术/量价/资金流因子"},
    )
