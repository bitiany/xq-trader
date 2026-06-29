"""个股新闻与公告 ORM 模型 — 存储东方财富新闻/巨潮公告采集数据。

数据源：
  - 新闻：akshare stock_news_em（东方财富新闻频道）
  - 公告：akshare stock_individual_notice_report（巨潮/东财公告）

合并为单表，用 news_type 字段区分类型，避免表数量膨胀。
唯一键：news_url（原文链接，URL 哈希去重）
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase


class StockNews(AuditedBase):
    """个股新闻与公告表 — akshare 采集产物。"""

    __bind_key__ = "stock"
    __tablename__ = "sdc_stock_news"

    symbol: Mapped[str] = mapped_column(String(20), nullable=False, comment="标的代码")
    news_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="类型：news=新闻 / announcement=公告")
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="标题")
    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="正文内容")
    source: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="来源（如东方财富/巨潮网）")
    news_url: Mapped[str] = mapped_column(String(512), nullable=False, comment="原文链接")
    publish_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="发布时间")
    keywords: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True, comment="关键词列表 JSONB（字符串数组）",
    )

    __table_args__ = (
        UniqueConstraint("news_url", name="uq_sdc_stock_news_url"),
        {"comment": "个股新闻与公告表 — akshare 采集产物"},
    )
