from datetime import date

from sqlalchemy import Date, Float, Integer, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base
from framework.dal.timescale import timescale


@timescale(
    time_column="trade_date",
    chunk_interval="3 month",
    compress_after="6 months",
    compress_segmentby="sector_code"
)
class FundFlowSector(Base):
    __bind_key__ = "stock"
    __tablename__ = "sdc_fund_flow_sector"

    sector_code: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="板块编码，DC为ts_code，QMT为申万编码"
    )
    sector_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="板块名称")
    sector_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="板块类型: industry/concept/region"
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, comment="交易日期")
    period: Mapped[str] = mapped_column(
        String(5), nullable=False, default="1d", comment="聚合周期: 1d"
    )

    close: Mapped[float | None] = mapped_column(Float, nullable=True, comment="板块指数收盘价")
    pct_change: Mapped[float | None] = mapped_column(Float, nullable=True, comment="涨跌幅(%)")

    main_net_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="主力净流入额(元)")
    main_net_pct: Mapped[float | None] = mapped_column(Float, nullable=True, comment="主力净流入占比(%)")

    huge_net_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="超大单净流入额(元)")
    huge_net_pct: Mapped[float | None] = mapped_column(Float, nullable=True, comment="超大单净流入占比(%)")

    big_net_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="大单净流入额(元)")
    big_net_pct: Mapped[float | None] = mapped_column(Float, nullable=True, comment="大单净流入占比(%)")

    mid_net_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="中单净流入额(元)")
    mid_net_pct: Mapped[float | None] = mapped_column(Float, nullable=True, comment="中单净流入占比(%)")

    small_net_amt: Mapped[float | None] = mapped_column(Float, nullable=True, comment="小单净流入额(元)")
    small_net_pct: Mapped[float | None] = mapped_column(Float, nullable=True, comment="小单净流入占比(%)")

    lead_stock: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="主力净流入最大股"
    )
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="排名序号")

    source: Mapped[str] = mapped_column(
        String(10), nullable=False, default="dc", comment="数据来源: dc(东财)/qmt(申万)"
    )

    __table_args__ = (
        PrimaryKeyConstraint(
            "sector_code", "trade_date", "period", "source",
            name="pk_ffs_sector_date_period_source",
        ),
        {"comment": "板块资金流向表 - 存储行业/概念/地域板块资金流向数据"},
    )
