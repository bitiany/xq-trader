"""券商研报 ORM 模型 — 存储东方财富研报中心采集的个股/行业研报元数据与摘要。

数据源：东方财富研报中心 HTTP API（data.eastmoney.com/report/）
唯一键：info_code（东财研报唯一标识，形如 AP202606291826552423）
PDF 文件：本地存储于 D:\\app\\volumes\\workspace\\report\\{symbol}\\ 下，pdf_path 字段记录相对路径。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import Boolean, Date, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase


class ResearchReport(AuditedBase):
    """券商研报表 — 东财研报中心采集产物。"""

    __bind_key__ = "stock"
    __tablename__ = "sdc_research_report"

    info_code: Mapped[str] = mapped_column(String(64), nullable=False, comment="东财研报唯一标识")
    symbol: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="标的代码（行业研报可空）")
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="研报标题")
    org_name: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="研究机构名称")
    researcher: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="分析师姓名")
    rating: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="评级（买入/增持/中性/减持/卖出）",
    )
    rating_change: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="评级变动（首次/维持/调高/调低）",
    )
    publish_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="研报发布日期")
    industry: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="所属行业")
    eps_forecast: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True, comment="盈利预测 JSONB（年度/EPS/PE 数组）",
    )
    pdf_url: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="研报 PDF 下载链接")
    pdf_path: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="本地 PDF 相对路径（相对 WORKSPACE_ROOT）",
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="研报摘要")
    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="研报全文（从 PDF 解析，可选）")
    vector_indexed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="研报全文是否已向量化入库 Qdrant（research_report_chunks collection）",
    )

    __table_args__ = (
        UniqueConstraint("info_code", name="uq_sdc_research_report_info_code"),
        {"comment": "券商研报表 — 东财研报中心采集产物"},
    )
