from datetime import date

from sqlalchemy import Date, Float, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base
from framework.dal.timescale import timescale


@timescale(
    time_column="trade_date",
    chunk_interval="3 month",
    compress_after="6 months",
    compress_segmentby="symbol"
)
class FundFlowIndividual(Base):
    """个股资金流向表 - 存储个股每日资金流向数据。

    数据源: tushare moneyflow接口。主力=超大单+大单。
    净流入占比 = 净流入额/(买入额+卖出额)*100。
    *_net_pct、close、pct_change 字段在 moneyflow 接口中未提供，恒为 NULL，
    可通过 buy_amt/sell_amt 计算得出。

    单笔成交额分类: 超大单>=100万, 大单20~100万, 中单5~20万, 小单<5万。
    """

    __bind_key__ = "stock"
    __tablename__ = "sdc_fund_flow_individual"

    symbol: Mapped[str] = mapped_column(String(20), nullable=False, comment="证券代码，如000001.SZ")
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, comment="交易日期")
    close: Mapped[float | None] = mapped_column(Float, nullable=True, comment="收盘价（moneyflow接口未提供，恒为NULL）")
    pct_change: Mapped[float | None] = mapped_column(Float, nullable=True, comment="涨跌幅(%)（moneyflow接口未提供，恒为NULL）")

    main_net_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="主力净流入额(万元) = 超大单净流入 + 大单净流入")
    main_net_pct: Mapped[float | None] = mapped_column(Float, nullable=True, comment="主力净流入占比(%) = main_net_amt/(主力买入额+主力卖出额)*100（恒为NULL，可由buy/sell_amt计算）")

    huge_buy_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="超大单买入额(万元)，单笔成交额>=100万")
    huge_sell_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="超大单卖出额(万元)，单笔成交额>=100万")
    huge_net_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="超大单净流入额(万元) = huge_buy_amt - huge_sell_amt")
    huge_net_pct: Mapped[float | None] = mapped_column(Float, nullable=True, comment="超大单净流入占比(%) = huge_net_amt/(huge_buy_amt+huge_sell_amt)*100（恒为NULL，可由buy/sell_amt计算）")

    big_buy_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="大单买入额(万元)，单笔成交额20万~100万")
    big_sell_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="大单卖出额(万元)，单笔成交额20万~100万")
    big_net_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="大单净流入额(万元) = big_buy_amt - big_sell_amt")
    big_net_pct: Mapped[float | None] = mapped_column(Float, nullable=True, comment="大单净流入占比(%) = big_net_amt/(big_buy_amt+big_sell_amt)*100（恒为NULL，可由buy/sell_amt计算）")

    mid_buy_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="中单买入额(万元)，单笔成交额5万~20万")
    mid_sell_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="中单卖出额(万元)，单笔成交额5万~20万")
    mid_net_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="中单净流入额(万元) = mid_buy_amt - mid_sell_amt")
    mid_net_pct: Mapped[float | None] = mapped_column(Float, nullable=True, comment="中单净流入占比(%) = mid_net_amt/(mid_buy_amt+mid_sell_amt)*100（恒为NULL，可由buy/sell_amt计算）")

    small_buy_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="小单买入额(万元)，单笔成交额<5万")
    small_sell_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="小单卖出额(万元)，单笔成交额<5万")
    small_net_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="小单净流入额(万元) = small_buy_amt - small_sell_amt")
    small_net_pct: Mapped[float | None] = mapped_column(Float, nullable=True, comment="小单净流入占比(%) = small_net_amt/(small_buy_amt+small_sell_amt)*100（恒为NULL，可由buy/sell_amt计算）")

    net_mf_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="全部净流入额(万元) = 全部买入 - 全部卖出")

    source: Mapped[str] = mapped_column(
        String(10), nullable=False, default="tushare", comment="数据来源: tushare/akshare"
    )

    __table_args__ = (
        PrimaryKeyConstraint("symbol", "trade_date", "source", name="pk_ffi_symbol_date_source"),
        {"comment": "个股资金流向表 - 数据源tushare moneyflow接口，主力=超大单+大单，净流入占比=净流入额/(买入额+卖出额)*100"},
    )
