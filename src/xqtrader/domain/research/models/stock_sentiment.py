"""市场舆情快照 ORM 模型 — 存储微博财经舆情、市场情绪等聚合数据。

数据源：
  - akshare stock_js_weibo_report（微博财经舆情报告）

特点：与新闻（事件级单条）不同，舆情快照是某日的聚合统计（热度/情感分/正负面提及数）。
symbol 列 NOT NULL DEFAULT ''：市场级舆情无对应标的，用空串占位，
  保证复合唯一约束 (snapshot_date, sentiment_type, symbol) 可正确去重。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import Date, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase


class StockSentiment(AuditedBase):
    """市场舆情快照表 — akshare 舆情接口采集产物。"""

    __bind_key__ = "stock"
    __tablename__ = "sdc_stock_sentiment"

    symbol: Mapped[str] = mapped_column(
        String(20), nullable=False, default="", server_default="",
        comment="标的代码（市场级舆情为空串占位）",
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, comment="快照日期")
    sentiment_type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="舆情类型：weibo=微博/market=市场/stock=个股",
    )
    heat_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="热度评分（0-100）")
    sentiment_score: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="情感评分（-1~1，负=消极/正=积极）",
    )
    positive_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="正面提及数")
    negative_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="负面提及数")
    neutral_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="中性提及数")
    keywords: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True, comment="热门关键词 JSONB（word/count 对象数组）",
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="舆情摘要")

    __table_args__ = (
        UniqueConstraint(
            "snapshot_date", "sentiment_type", "symbol",
            name="uq_sdc_stock_sentiment_date_type_symbol",
        ),
        {"comment": "市场舆情快照表 — akshare 舆情接口采集产物"},
    )
