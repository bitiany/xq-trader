"""样本池配置表 — fac_factor_pool。

指数样本池从 sdc_index_weight 读取成分股；
行业/风格样本池通过 definition 规则动态计算。
"""

from sqlalchemy import Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase


class FacFactorPool(AuditedBase):
    """样本池配置表。"""

    __bind_key__ = "research"
    __tablename__ = "fac_factor_pool"

    pool_id: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, comment="样本池标识: idx_300/style_growth等"
    )
    pool_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="展示名: 沪深300/成长股等"
    )
    pool_type: Mapped[str] = mapped_column(
        String(16), nullable=False,
        comment="样本池类型: index/industry/style",
    )
    definition: Mapped[dict] = mapped_column(
        JSONB, nullable=True,
        comment="样本池定义规则: {type:'index', index_code:'000300.SH'} 等",
    )
    refresh_freq: Mapped[str] = mapped_column(
        String(16), nullable=False, default="quarterly",
        comment="刷新频率: daily/weekly/quarterly",
    )
    status: Mapped[str] = mapped_column(
        String(8), nullable=False, default="active",
        comment="状态: active/deprecated",
    )

    __table_args__ = (
        Index("ix_fac_pool_type", "pool_type"),
        Index("ix_fac_pool_status", "status"),
        {"comment": "样本池配置表 — 定义因子评估的标的范围"},
    )
