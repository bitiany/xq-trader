"""因子注册表 — 因子元数据持久化，代码声明为唯一真相源，启动时同步。"""

from sqlalchemy import Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase


class FacFactorRegistry(AuditedBase):
    """因子注册表 — 存储因子元数据和运行时状态。"""

    __bind_key__ = "research"
    __tablename__ = "fac_factor_registry"

    factor_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, comment="因子标识")
    display_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="因子显示名称")
    category: Mapped[str] = mapped_column(String(32), nullable=False, comment="因子分类")
    group_id: Mapped[str] = mapped_column(String(32), nullable=True, default="", comment="组合因子组ID")
    direction: Mapped[str] = mapped_column(String(8), nullable=True, default="DESC", comment="因子方向 DESC/ASC")
    scope: Mapped[str] = mapped_column(String(16), nullable=True, default="both", comment="适用范围 long/short/both")
    signal_type: Mapped[str] = mapped_column(String(16), nullable=True, default="continuous", comment="信号类型")
    base_factor: Mapped[str] = mapped_column(String(32), nullable=True, default="", comment="基础因子")
    dependencies: Mapped[str] = mapped_column(String(256), nullable=True, default="", comment="依赖列，逗号分隔")
    min_periods: Mapped[int] = mapped_column(Integer, nullable=True, default=1, comment="最小计算周期")
    compute_module: Mapped[str] = mapped_column(
        String(256), nullable=True, default="", comment="计算模块路径 module:Class",
    )
    params: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default={}, comment="计算参数 JSON")
    data_origin: Mapped[str] = mapped_column(String(32), nullable=True, default="computed", comment="数据来源")
    update_freq: Mapped[str] = mapped_column(String(16), nullable=True, default="daily", comment="更新频率")
    compute_engine: Mapped[str] = mapped_column(String(16), nullable=True, default="plugin", comment="计算引擎")
    tags: Mapped[str] = mapped_column(String(128), nullable=True, default="", comment="标签")
    status: Mapped[str] = mapped_column(
        String(16), nullable=True, default="draft",
        comment="状态 draft/testing/active/deprecated",
    )
    factor_grade: Mapped[str | None] = mapped_column(String(2), nullable=True, default=None, comment="因子等级 A/B/C/D")
    report_lag_days: Mapped[int] = mapped_column(Integer, nullable=True, default=0, comment="财报发布滞后天数")
    is_composite: Mapped[int] = mapped_column(Integer, nullable=True, default=0, comment="是否组合因子 0/1")
    composite_factor_ids: Mapped[str] = mapped_column(
        String(256), nullable=True, default="", comment="组合因子子ID，逗号分隔",
    )
    skip_preprocess: Mapped[int] = mapped_column(Integer, nullable=True, default=0, comment="是否跳过预处理 0/1")
    description: Mapped[str] = mapped_column(String(256), nullable=True, default="", comment="因子描述")

    __table_args__ = (
        {"comment": "因子注册表 — 元数据+运行时状态"},
    )
