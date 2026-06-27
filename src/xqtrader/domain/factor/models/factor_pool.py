"""样本池配置表 — 定义因子评估的标的范围和因子范围。

样本池按类型分为指数池、行业池、风格池，评估任务按 pool_id 维度分别计算统计指标。
- definition: 定义标的范围（如 index_code、industry_code、tag_key）
- factor_scope: 定义该池评估的因子范围（null=全量，include/exclude/category 模式）
"""

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase


class FacFactorPool(AuditedBase):
    """样本池配置表。"""

    __bind_key__ = "research"
    __tablename__ = "fac_factor_pool"

    pool_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, comment="样本池标识")
    pool_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="样本池名称")
    pool_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="样本池类型 index/industry/style")
    definition: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="样本池定义规则 JSON")
    factor_scope: Mapped[dict | None] = mapped_column(
        JSON, nullable=True,
        comment="因子评估范围 JSON: null=全量, {include:[...]}/{exclude:[...]}/{category:[...]}",
    )
    refresh_freq: Mapped[str] = mapped_column(String(16), nullable=True, default="daily", comment="刷新频率")
    status: Mapped[str] = mapped_column(String(16), nullable=True, default="active", comment="状态 active/deprecated")

    __table_args__ = (
        {"comment": "样本池配置表 — 定义因子评估的标的范围和因子范围"},
    )
