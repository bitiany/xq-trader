"""因子统计指标表 — 存储因子评估结果（IC/ICIR/分层回测/等级等）。

按 factor_id × pool_id × calc_date 维度存储，同一因子在不同样本池下有独立的统计指标。
"""

from datetime import date

from sqlalchemy import Date, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase


class FacFactorStats(AuditedBase):
    """因子统计指标表 — 评估管线产出。"""

    __bind_key__ = "research"
    __tablename__ = "fac_factor_stats"

    factor_id: Mapped[str] = mapped_column(String(32), nullable=False, comment="因子标识")
    pool_id: Mapped[str] = mapped_column(String(16), nullable=False, comment="样本池标识")
    calc_date: Mapped[date] = mapped_column(Date, nullable=False, comment="计算日期")
    window: Mapped[int] = mapped_column(Integer, nullable=False, default=252, comment="滚动窗口(交易日)")
    ic_mean: Mapped[float | None] = mapped_column(Float, nullable=True, comment="IC均值")
    ic_std: Mapped[float | None] = mapped_column(Float, nullable=True, comment="IC标准差")
    icir: Mapped[float | None] = mapped_column(Float, nullable=True, comment="ICIR = IC_mean / IC_std")
    ic_win_rate: Mapped[float | None] = mapped_column(Float, nullable=True, comment="IC胜率")
    turnover: Mapped[float | None] = mapped_column(Float, nullable=True, comment="换手率")
    decay_half_life: Mapped[float | None] = mapped_column(Float, nullable=True, comment="IC衰减半衰期(日)")
    long_short_annual_ret: Mapped[float | None] = mapped_column(Float, nullable=True, comment="多空年化收益率")
    long_short_sharpe: Mapped[float | None] = mapped_column(Float, nullable=True, comment="多空夏普比率")
    coverage: Mapped[float | None] = mapped_column(Float, nullable=True, comment="因子覆盖度")
    factor_grade: Mapped[str | None] = mapped_column(String(2), nullable=True, comment="因子等级 A/B/C/D")

    __table_args__ = (
        {"comment": "因子统计指标表 — 评估管线产出"},
    )
