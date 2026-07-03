"""投研论点卡 — per-symbol 慢变量结论

设计原则:
  - 五步法基本面推演的持久化产物（信息差/逻辑差/超预期差/催化剂/方向/证伪条件）
  - 慢时钟：事件驱动（财报/重大公告）或证伪驱动或到期驱动失效
  - 可缓存「判断」，不可缓存「数字」——引用数字时须实时校验
  - status=active 时可直接引用，status=stale 时须重跑五步法
"""

from datetime import date

from sqlalchemy import Date, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase


class ResearchThesis(AuditedBase):
    """投研论点卡 — 国泰君安五步法基本面结论（per-symbol 慢变量）"""

    __bind_key__ = "default"
    __tablename__ = "ag_research_thesis"

    symbol: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True, comment="股票代码",
    )
    as_of: Mapped[date] = mapped_column(
        Date, nullable=False, comment="数据截至日",
    )
    valid_until: Mapped[date] = mapped_column(
        Date, nullable=False, comment="时间失效边界（到期自动 stale）",
    )
    direction: Mapped[str] = mapped_column(
        String(8), nullable=False, comment="基本面方向: 关注/观望/谨慎",
    )
    info_gap: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="信息差: 市场未充分定价的边际信息",
    )
    logic_gap: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="逻辑差: 主流逻辑 vs 差异逻辑 + 自洽性",
    )
    surprise_gap: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="超预期差: 一致预期 vs 差异推演",
    )
    catalysts: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="催化剂: 事件清单 + 时间轴",
    )
    core_assumption: Mapped[str] = mapped_column(
        Text, nullable=False, comment="核心假设",
    )
    falsification: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="证伪条件（同时是缓存失效判据）",
    )
    tracking_metrics: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="跟踪指标清单",
    )
    invalidation_rules: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="失效规则: 事件/证伪/时间触发器",
    )
    status: Mapped[str] = mapped_column(
        String(8), nullable=False, default="active", comment="状态: active/stale",
    )
