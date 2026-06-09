from sqlalchemy import Date, Float, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base
from framework.dal.timescale import timescale


@timescale(
    time_column="trade_date",
    chunk_interval="6 month",
    compress_after="12 months",
    compress_segmentby="symbol",
)
class IndexDaily(Base):
    __bind_key__ = "stock"
    __tablename__ = "sdc_index_daily"

    symbol: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="指数代码，如000001.SH",
    )
    trade_date: Mapped[str] = mapped_column(
        Date, nullable=False, comment="交易日期",
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
    pre_close: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="昨日收盘点位",
    )
    change: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="涨跌点位",
    )
    pct_chg: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="涨跌幅(%)",
    )
    vol: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="成交量(手)",
    )
    amount: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="成交额(千元)",
    )
    source: Mapped[str] = mapped_column(
        String(10), nullable=False, default="tushare", comment="数据来源",
    )

    __table_args__ = (
        PrimaryKeyConstraint(
            "symbol", "trade_date", "source",
            name="pk_id_symbol_date_source",
        ),
        {"comment": "指数日行情表 - 存储指数日线行情数据"},
    )
