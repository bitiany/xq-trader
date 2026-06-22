from sqlalchemy import Date, Float, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base
from framework.dal.timescale import timescale


@timescale(
    time_column="trade_date",
    chunk_interval="6 month",
    compress_after="12 months",
    compress_segmentby="ts_code",
)
class SwDaily(Base):
    __bind_key__ = "stock"
    __tablename__ = "sdc_sw_daily"

    ts_code: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="指数代码，如801010.SI",
    )
    trade_date: Mapped[str] = mapped_column(
        Date, nullable=False, comment="交易日期",
    )
    name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="指数名称",
    )
    open: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="开盘点位",
    )
    high: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="最高点位",
    )
    low: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="最低点位",
    )
    close: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="收盘点位",
    )
    change: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="涨跌点位",
    )
    pct_change: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="涨跌幅",
    )
    vol: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="成交量（万股）",
    )
    amount: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="成交额（万元）",
    )
    pe: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="市盈率",
    )
    pb: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="市净率",
    )
    float_mv: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="流通市值（万元）",
    )
    total_mv: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="总市值（万元）",
    )
    source: Mapped[str] = mapped_column(
        String(10), nullable=False, default="tushare", comment="数据来源",
    )

    __table_args__ = (
        PrimaryKeyConstraint(
            "ts_code", "trade_date", "source",
            name="pk_swd_tscode_date_source",
        ),
        {"comment": "申万行业指数日行情表 - 存储申万行业指数日线行情数据"},
    )
