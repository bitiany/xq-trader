
from sqlalchemy import Date, Float, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base
from framework.dal.timescale import timescale


@timescale(
    time_column="trade_date",
    chunk_interval="1 month",
    compress_after="3 months",
    compress_segmentby="symbol"
)
class DailyIndicator(Base):
    __bind_key__ = "stock"
    __tablename__ = "sdc_daily_indicator"

    symbol: Mapped[str] = mapped_column(String(20), nullable=False, comment="证券代码，如000001")
    trade_date: Mapped[Date] = mapped_column(Date, nullable=False, comment="交易日期")
    close: Mapped[float] = mapped_column(Float, nullable=False, comment="当日收盘价")
    turnover_rate: Mapped[float | None] = mapped_column(Float, nullable=True, comment="换手率(%)")
    turnover_rate_f: Mapped[float | None] = mapped_column(Float, nullable=True, comment="流通换手率(%)")
    volume_ratio: Mapped[float | None] = mapped_column(Float, nullable=True, comment="量比")
    pe: Mapped[float | None] = mapped_column(Float, nullable=True, comment="市盈率(动态)")
    pe_ttm: Mapped[float | None] = mapped_column(Float, nullable=True, comment="市盈率(TTM)")
    pb: Mapped[float | None] = mapped_column(Float, nullable=True, comment="市净率")
    ps: Mapped[float | None] = mapped_column(Float, nullable=True, comment="市销率(动态)")
    ps_ttm: Mapped[float | None] = mapped_column(Float, nullable=True, comment="市销率(TTM)")
    dv_ratio: Mapped[float | None] = mapped_column(Float, nullable=True, comment="股息率(%)")
    dv_ttm: Mapped[float | None] = mapped_column(Float, nullable=True, comment="股息率TTM(%)")
    total_share: Mapped[float | None] = mapped_column(Float, nullable=True, comment="总股本(万股)")
    float_share: Mapped[float | None] = mapped_column(Float, nullable=True, comment="流通股本(万股)")
    free_share: Mapped[float | None] = mapped_column(Float, nullable=True, comment="自由流通股本(万股)")
    total_mv: Mapped[float | None] = mapped_column(Float, nullable=True, comment="总市值(万元)")
    circ_mv: Mapped[float | None] = mapped_column(Float, nullable=True, comment="流通市值(万元)")
    ev: Mapped[float | None] = mapped_column(Float, nullable=True, comment="企业价值(万元)")
    ebitda: Mapped[float | None] = mapped_column(Float, nullable=True, comment="息税折旧摊销前利润(万元)")
    ev_ebitda: Mapped[float | None] = mapped_column(Float, nullable=True, comment="企业价值倍数(EV/EBITDA)")
    peg: Mapped[float | None] = mapped_column(Float, nullable=True, comment="市盈增长比率(PEG)")
    pcf: Mapped[float | None] = mapped_column(Float, nullable=True, comment="市现率(PCF)")

    __table_args__ = (
        PrimaryKeyConstraint("symbol", "trade_date", name="pk_daily_indicator_symbol_trade_date"),
        {"comment": "每日指标表 - 存储股票每日交易指标(估值/换手率/市值等)"},
    )
