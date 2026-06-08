"""个股资金流向 ORM 模型。"""

from datetime import date

from sqlalchemy import Date, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base
from framework.dal.timescale import timescale


@timescale(
    time_column="trade_date",
    chunk_interval="6 month",
    compress_after="12 months",
    compress_segmentby="symbol",
)
class FundFlowIndividual(Base):
    """个股资金流向表"""

    __bind_key__ = "stock"
    __tablename__ = "sdc_fund_flow_individual"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True, nullable=False, comment="证券代码")
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True, nullable=False, comment="交易日期")
    source: Mapped[str] = mapped_column(String(10), primary_key=True, nullable=False, comment="数据来源")
    close: Mapped[float | None] = mapped_column(Float, nullable=True, comment="收盘价")
    pct_change: Mapped[float | None] = mapped_column(Float, nullable=True, comment="涨跌幅")
    main_net_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="主力净流入额")
    main_net_pct: Mapped[float | None] = mapped_column(Float, nullable=True, comment="主力净流入占比")
    huge_buy_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="超大单买入额")
    huge_sell_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="超大单卖出额")
    huge_net_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="超大单净流入额")
    huge_net_pct: Mapped[float | None] = mapped_column(Float, nullable=True, comment="超大单净流入占比")
    big_buy_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="大单买入额")
    big_sell_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="大单卖出额")
    big_net_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="大单净流入额")
    big_net_pct: Mapped[float | None] = mapped_column(Float, nullable=True, comment="大单净流入占比")
    mid_buy_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="中单买入额")
    mid_sell_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="中单卖出额")
    mid_net_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="中单净流入额")
    mid_net_pct: Mapped[float | None] = mapped_column(Float, nullable=True, comment="中单净流入占比")
    small_buy_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="小单买入额")
    small_sell_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="小单卖出额")
    small_net_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="小单净流入额")
    small_net_pct: Mapped[float | None] = mapped_column(Float, nullable=True, comment="小单净流入占比")
    net_mf_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="净流入额")

    __table_args__ = ({"comment": "个股资金流向表"},)
