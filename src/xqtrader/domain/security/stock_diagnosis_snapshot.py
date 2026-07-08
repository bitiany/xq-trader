"""个股诊股评分快照 ORM — 五维雷达与综合得分日频存储。"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import Date, Float, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase


class StockDiagnosisSnapshot(AuditedBase):
    """个股诊股评分快照表。"""

    __bind_key__ = "stock"
    __tablename__ = "sdc_stock_diagnosis_snapshot"

    symbol: Mapped[str] = mapped_column(String(20), nullable=False, comment="标的代码")
    as_of: Mapped[date] = mapped_column(Date, nullable=False, comment="评分基准日")
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="综合得分 0-10")
    earnings_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="收益预测维度分")
    momentum_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="价格动量维度分")
    fundamental_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="基本面维度分")
    valuation_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="相对估值维度分")
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="风险维度分")
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, comment="子分明细与关键指标")
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, comment="变化解读")

    __table_args__ = (
        UniqueConstraint("symbol", "as_of", name="uq_sdc_stock_diagnosis_snapshot_symbol_as_of"),
        {"comment": "个股诊股评分快照 — 五维雷达与综合得分"},
    )
