from datetime import date

from sqlalchemy import Date, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base
from framework.dal.timescale import timescale


@timescale(
    time_column="trade_date",
    chunk_interval="6 month",
    compress_after="12 months",
    compress_segmentby="symbol"
)
class CandlestickDaily(Base):
    __bind_key__ = "stock"
    __tablename__ = "sdc_candlestick_daily"

    symbol: Mapped[str] = mapped_column(String(10), primary_key=True, nullable=False, comment="证券代码，如000001.SH")
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True, nullable=False, comment="交易日期")
    open: Mapped[float] = mapped_column(Float, nullable=False, comment="开盘价")
    close: Mapped[float] = mapped_column(Float, nullable=False, comment="收盘价")
    high: Mapped[float] = mapped_column(Float, nullable=False, comment="最高价")
    low: Mapped[float] = mapped_column(Float, nullable=False, comment="最低价")
    volume: Mapped[int] = mapped_column(Integer, nullable=False, comment="成交量(手)")
    amount: Mapped[float] = mapped_column(Float, nullable=False, comment="成交额(千元)")
    change: Mapped[float] = mapped_column(Float, nullable=True, comment="涨跌额")
    pre_close: Mapped[float] = mapped_column(Float, nullable=True, comment="前收盘价")
    pct_chg: Mapped[float] = mapped_column(Float, nullable=True, comment="涨跌幅(%)")
    data_source: Mapped[str] = mapped_column(String(20), nullable=True, default="qmt", comment="数据来源: qmt/tushare")

    __table_args__ = (
        {"comment": "K线行情表 - 存储股票日K线数据"},
    )
