"""季频因子统计指标表 — 季频评估管线产出。

按 factor_id × pool_id × calc_date × ann_window 维度存储。
评估锚点为报告期（ann_date），window 为季度数（8Q/12Q/16Q/20Q）。
与日频评估表 fac_factor_stats 完全分离，独立持久化。
"""

from datetime import date
from typing import Any

from sqlalchemy import Date, Float, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase


class FacFinancialFactorStats(AuditedBase):
    """季频因子统计指标表 — 季频评估管线产出。

    与 fac_factor_stats 的区别：
      - 评估锚点：ann_date（报告期），非交易日
      - 窗口单位：季度数（8/12/16/20），非交易日
      - IC horizon：1Q/2Q/4Q（季频前向收益），非 1d/5d/10d/20d
      - 衰减半衰期：季度单位，非日单位
    """

    __bind_key__ = "research"
    __tablename__ = "fac_financial_factor_stats"

    factor_id: Mapped[str] = mapped_column(String(32), nullable=False, comment="因子标识")
    pool_id: Mapped[str] = mapped_column(String(16), nullable=False, comment="样本池标识")
    calc_date: Mapped[date] = mapped_column(Date, nullable=False, comment="计算日期（最新交易日）")
    ann_window: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20, comment="IC统计窗口(季度数，8/12/16/20)",
    )

    # IC 指标（与未来 1Q 收益的 IC）
    ic_mean: Mapped[float | None] = mapped_column(Float, nullable=True, comment="IC均值")
    ic_std: Mapped[float | None] = mapped_column(Float, nullable=True, comment="IC标准差")
    icir: Mapped[float | None] = mapped_column(Float, nullable=True, comment="ICIR = IC_mean / IC_std")
    ic_win_rate: Mapped[float | None] = mapped_column(Float, nullable=True, comment="IC胜率")
    ic_mean_2q: Mapped[float | None] = mapped_column(Float, nullable=True, comment="2季度前向收益IC均值")
    ic_mean_4q: Mapped[float | None] = mapped_column(Float, nullable=True, comment="4季度前向收益IC均值")
    ic_tstat: Mapped[float | None] = mapped_column(Float, nullable=True, comment="IC均值t统计量")
    ic_pvalue: Mapped[float | None] = mapped_column(Float, nullable=True, comment="IC均值p值")

    # 分层回测
    long_short_annual_ret: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="多空年化收益率",
    )
    long_short_sharpe: Mapped[float | None] = mapped_column(Float, nullable=True, comment="多空夏普比率")
    group_returns: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment='分层回测各组年化收益 JSONB: {"Q1":..,"Q5":..}',
    )

    # 其他
    turnover: Mapped[float | None] = mapped_column(Float, nullable=True, comment="季频换手率")
    decay_half_life: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="IC衰减半衰期(季度)",
    )
    coverage: Mapped[float | None] = mapped_column(Float, nullable=True, comment="因子覆盖度")
    factor_grade: Mapped[str | None] = mapped_column(
        String(2), nullable=True, comment="因子等级 A/B/C/D",
    )
    ic_decay_curve: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True, comment='IC衰减曲线 JSONB: [{"h":1,"ic":0.05},...]',
    )

    __table_args__ = (
        UniqueConstraint(
            "factor_id", "pool_id", "calc_date", "ann_window",
            name="uq_fin_fac_stats_fid_pid_cd_aw",
        ),
        {"comment": "季频因子统计指标表 — 季频评估管线产出"},
    )
