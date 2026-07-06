"""季频合成因子值窄表 — 存储季频合成因子的逐标的值。

与 fac_factor_value 的区别：
  - 按 ann_date（公告日）存储，非 trade_date
  - 仅存储季频合成因子（composite_*_quarterly），非日频因子
  - 普通表（非 TimescaleDB hypertable），数据量小（32 因子 × 5294 symbols × 28 季度 ≈ 4.7M rows）
"""

from datetime import date

from sqlalchemy import Date, Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base


class FacFinancialCompositeValue(Base):
    """季频合成因子值窄表 — 按 ann_date 存储季频合成因子。"""

    __bind_key__ = "stock"
    __tablename__ = "fac_financial_composite_value"

    symbol: Mapped[str] = mapped_column(
        String(10), primary_key=True, nullable=False, comment="证券代码",
    )
    ann_date: Mapped[date] = mapped_column(
        Date, primary_key=True, nullable=False, comment="公告日期（PIT依据）",
    )
    factor_id: Mapped[str] = mapped_column(
        String(32), primary_key=True, nullable=False, comment="因子标识",
    )
    pool_id: Mapped[str] = mapped_column(
        String(16), primary_key=True, nullable=False, comment="样本池标识，默认all",
    )
    factor_value: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="合成因子值（截面标准化后）",
    )

    __table_args__ = (
        Index("ix_fin_comp_val_ann_fid", "ann_date", "factor_id"),
        Index("ix_fin_comp_val_sym_ann", "symbol", "ann_date"),
        Index("ix_fin_comp_val_fid_pid", "factor_id", "pool_id"),
        {"comment": "季频合成因子值窄表 — 按 ann_date 存储季频合成因子"},
    )
