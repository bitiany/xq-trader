from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import UniqueConstraint

from framework.dal.base import Base


class CollectWatermark(Base):
    __bind_key__ = "default"
    __tablename__ = "t_collect_watermark"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键")
    data_type: Mapped[str] = mapped_column(String(100), nullable=False, comment="数据类型，如daily_kline、fund_flow")
    watermark_code: Mapped[str] = mapped_column(String(20), nullable=False, comment="水位标识代码，如000001.SZ")
    watermark_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="最新采集日期，NULL表示未采集")
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="累计采集记录数")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active",
        comment="水位状态: active-正常, deprecated-废弃",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
        comment="更新时间",
    )

    __table_args__ = (
        UniqueConstraint("data_type", "watermark_code", name="uq_watermark_data_type_code"),
        {"comment": "采集水位表 - 记录每种数据类型每支标的的最新采集日期"},
    )
