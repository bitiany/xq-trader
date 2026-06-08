"""新因子注册表 — fac_factor_registry。

与旧表 sdc_factor_registry 隔离，新增 factor_grade / update_freq / report_lag_days 字段。
"""

from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase


class FacFactorRegistry(AuditedBase):
    """新因子注册表（代码声明为唯一真相源，运行时状态持久化到此表）。"""

    __bind_key__ = "research"
    __tablename__ = "fac_factor_registry"

    factor_id: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, comment="因子唯一标识"
    )
    display_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="展示名"
    )
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="大类: risk/fundamental/technical/quantitative/chan/candlestick/alpha"
    )
    group_id: Mapped[str] = mapped_column(
        String(32), nullable=True, default="", comment="因子组"
    )
    direction: Mapped[str] = mapped_column(
        String(4), nullable=False, default="DESC", comment="排序方向: DESC/ASC"
    )
    scope: Mapped[str] = mapped_column(
        String(16), nullable=False, default="both",
        comment="作用域: cross_section/time_series/both",
    )
    signal_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="continuous",
        comment="信号类型: continuous/rank/percentile/threshold/categorical",
    )
    base_factor: Mapped[str] = mapped_column(
        String(32), nullable=True, default="", comment="派生来源因子ID"
    )
    dependencies: Mapped[str] = mapped_column(
        String(256), nullable=True, default="", comment="依赖字段(逗号分隔)"
    )
    min_periods: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, comment="最少K线数"
    )
    compute_module: Mapped[str] = mapped_column(
        String(128), nullable=True, default="", comment="计算模块路径"
    )
    params: Mapped[dict] = mapped_column(JSONB, nullable=True, comment="计算参数")
    data_origin: Mapped[str] = mapped_column(
        String(32), nullable=True, default="",
        comment="数据源: daily_indicator/fina_indicator/income/balance/cashflow/computed",
    )
    compute_engine: Mapped[str] = mapped_column(
        String(32), nullable=True, default="",
        comment="计算引擎: plugin/cross_field/cross_zscore/composite",
    )
    update_freq: Mapped[str] = mapped_column(
        String(16), nullable=False, default="daily",
        comment="更新频率: daily/daily_derived/quarterly/annual",
    )
    report_lag_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
        comment="财报发布滞后天数(仅quarterly因子需设置, ann_date缺失时兜底)",
    )
    tags: Mapped[str] = mapped_column(
        String(256), nullable=True, default="", comment="标签(逗号分隔)"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active",
        comment="状态: active/testing/watchlist/deprecated/dormant/archived",
    )
    factor_grade: Mapped[str] = mapped_column(
        String(2), nullable=True, default=None,
        comment="因子等级: A/B/C/D (评估后写入)",
    )
    description: Mapped[str] = mapped_column(
        Text, nullable=True, comment="因子描述"
    )

    __table_args__ = (
        Index("ix_fac_reg_category", "category"),
        Index("ix_fac_reg_status", "status"),
        Index("ix_fac_reg_grade", "factor_grade"),
        {"comment": "新因子注册表 — 因子元数据定义 + 运行时状态"},
    )
