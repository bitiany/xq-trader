from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Date, DateTime, Float, Integer, String, TypeDecorator
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base
from framework.dal.timescale import timescale

# A股交易时区：Asia/Shanghai (UTC+8)
_CST = timezone(timedelta(hours=8))


class CSTDateTime(TypeDecorator):
    """带时区的 DateTime，读取时自动转换为 Asia/Shanghai 时区

    PostgreSQL timestamptz 内部以 UTC 存储，asyncpg 默认返回 UTC datetime。
    本类型在 Python 端将 datetime 的 tzinfo 替换为 CST，使查询结果与本地时钟一致。
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=_CST)
        return value.astimezone(_CST)


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


@timescale(
    time_column="trade_time",
    chunk_interval="1 day",
    compress_after="3 months",
    compress_segmentby="symbol"
)
class CandlestickMinute(Base):
    """分钟级K线行情表 - 盘内实时监控用

    存储动态股票池的1分钟OHLCV数据，用于盘中信号计算与事后归因。
    5m/15m/30m/1h 周期通过 Continuous Aggregate 自动聚合，不需单独建表。
    """

    __bind_key__ = "stock"
    __tablename__ = "sdc_candlestick_1m"

    symbol: Mapped[str] = mapped_column(String(10), primary_key=True, nullable=False, comment="证券代码，如000001.SH")
    trade_time: Mapped[datetime] = mapped_column(
        CSTDateTime, primary_key=True, nullable=False, comment="分钟时间戳"
    )
    open: Mapped[float] = mapped_column(Float, nullable=False, comment="开盘价")
    high: Mapped[float] = mapped_column(Float, nullable=False, comment="最高价")
    low: Mapped[float] = mapped_column(Float, nullable=False, comment="最低价")
    close: Mapped[float] = mapped_column(Float, nullable=False, comment="收盘价")
    volume: Mapped[int] = mapped_column(Integer, nullable=False, comment="成交量(手)")
    amount: Mapped[float] = mapped_column(Float, nullable=False, comment="成交额(元)")
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True, comment="所属交易日，便于按日聚合查询")
    data_source: Mapped[str] = mapped_column(String(20), nullable=False, default="qmt", comment="数据来源: qmt/tushare")

    __table_args__ = (
        {"comment": "分钟级K线行情表 - 盘内实时监控用"},
    )
