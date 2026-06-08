"""因子统计指标表 — fac_factor_stats。

按 factor_id × pool_id 维度存储 IC/ICIR 等统计指标，每月更新。
"""

from datetime import date

from sqlalchemy import Date, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase


class FacFactorStats(AuditedBase):
    """因子统计指标表。"""

    __bind_key__ = "research"
    __tablename__ = "fac_factor_stats"

    factor_id: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="因子标识"
    )
    pool_id: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="样本池标识"
    )
    calc_date: Mapped[date] = mapped_column(
        Date, nullable=False, comment="计算日期"
    )
    window: Mapped[int] = mapped_column(
        Integer, nullable=False, default=252, comment="滚动窗口(交易日)"
    )
    ic_mean: Mapped[float] = mapped_column(
        Float, nullable=True, comment="IC均值(Spearman rank IC)"
    )
    ic_std: Mapped[float] = mapped_column(
        Float, nullable=True, comment="IC标准差"
    )
    icir: Mapped[float] = mapped_column(
        Float, nullable=True, comment="ICIR = ic_mean / ic_std"
    )
    ic_win_rate: Mapped[float] = mapped_column(
        Float, nullable=True, comment="IC胜率(IC>0的比例)"
    )
    turnover: Mapped[float] = mapped_column(
        Float, nullable=True, comment="因子换手率"
    )
    decay_half_life: Mapped[float] = mapped_column(
        Float, nullable=True, comment="IC衰减半衰期(交易日)"
    )
    long_short_annual_ret: Mapped[float] = mapped_column(
        Float, nullable=True, comment="多空年化收益率"
    )
    long_short_sharpe: Mapped[float] = mapped_column(
        Float, nullable=True, comment="多空Sharpe比率"
    )
    coverage: Mapped[float] = mapped_column(
        Float, nullable=True, comment="因子覆盖率"
    )
    factor_grade: Mapped[str] = mapped_column(
        String(2), nullable=True, comment="因子等级: A/B/C/D"
    )

    __table_args__ = (
        UniqueConstraint(
            "factor_id", "pool_id", "calc_date", "window",
            name="uq_fac_stats_factor_pool_date_window",
        ),
        Index("ix_fac_stats_factor_pool", "factor_id", "pool_id"),
        Index("ix_fac_stats_calc_date", "calc_date"),
        Index("ix_fac_stats_grade", "factor_grade"),
        {"comment": "因子统计指标表 — IC/ICIR/换手率/衰减/分层回测等"},
    )
