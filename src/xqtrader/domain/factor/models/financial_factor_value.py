"""季度财务因子值 — 按 ann_date 存储，不做前向填充。"""

from datetime import date

from sqlalchemy import Date, Float, Index, String, desc
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base


class FacFinancialFactorValue(Base):
    """季度财务因子值 — 按 ann_date 存储，不做前向填充。"""

    __bind_key__ = "stock"
    __tablename__ = "fac_financial_factor_value"

    symbol: Mapped[str] = mapped_column(String(10), primary_key=True, nullable=False, comment="证券代码")
    end_date: Mapped[date] = mapped_column(Date, primary_key=True, nullable=False, comment="财报期（如2025-12-31）")
    factor_id: Mapped[str] = mapped_column(String(32), primary_key=True, nullable=False, comment="因子标识")
    ann_date: Mapped[date] = mapped_column(Date, primary_key=True, nullable=False, comment="公告日期（PIT依据）")
    factor_value: Mapped[float | None] = mapped_column(Float, nullable=True, comment="因子原始值（未标准化）")

    __table_args__ = (
        Index("ix_fin_fac_val_ann_fid", "ann_date", "factor_id"),
        Index("ix_fin_fac_val_sym_end", "symbol", desc("end_date")),
        Index("ix_fin_fac_val_fid_end", "factor_id", "end_date"),
        {"comment": "季度财务因子值 — 按 ann_date 存储，不做前向填充"},
    )
