from sqlalchemy import Date, Float, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base
from framework.dal.timescale import timescale


@timescale(
    time_column="end_date",
    chunk_interval="12 month",
    compress_after="12 months",
    compress_segmentby="symbol"
)
class IncomeStatement(Base):
    __bind_key__ = "stock"
    __tablename__ = "sdc_income_statement"

    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True, comment="TS股票代码")
    ann_date: Mapped[str | None] = mapped_column(Date, nullable=True, index=True, comment="公告日期")
    f_ann_date: Mapped[str | None] = mapped_column(Date, nullable=True, comment="实际公告日期")
    end_date: Mapped[Date] = mapped_column(Date, nullable=False, index=True, comment="报告期")
    report_type: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="报表类型")
    comp_type: Mapped[str | None] = mapped_column(
        String(10), nullable=True, comment="公司类型(1一般工商业2银行3保险4证券)"
    )
    end_type: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="报告期类型")
    update_flag: Mapped[str | None] = mapped_column(String(1), nullable=True, comment="更新标识(1最新)")

    basic_eps: Mapped[float | None] = mapped_column(Float, nullable=True, comment="基本每股收益")
    diluted_eps: Mapped[float | None] = mapped_column(Float, nullable=True, comment="稀释每股收益")

    total_revenue: Mapped[float | None] = mapped_column(Float, nullable=True, comment="营业总收入")
    revenue: Mapped[float | None] = mapped_column(Float, nullable=True, comment="营业收入")
    oper_cost: Mapped[float | None] = mapped_column(Float, nullable=True, comment="营业成本")
    total_cogs: Mapped[float | None] = mapped_column(Float, nullable=True, comment="营业总成本")
    sell_exp: Mapped[float | None] = mapped_column(Float, nullable=True, comment="销售费用")
    admin_exp: Mapped[float | None] = mapped_column(Float, nullable=True, comment="管理费用")
    fin_exp: Mapped[float | None] = mapped_column(Float, nullable=True, comment="财务费用")
    assets_impair_loss: Mapped[float | None] = mapped_column(Float, nullable=True, comment="资产减值损失")
    credit_impa_loss: Mapped[float | None] = mapped_column(Float, nullable=True, comment="信用减值损失")

    invest_income: Mapped[float | None] = mapped_column(Float, nullable=True, comment="投资净收益")
    ass_invest_income: Mapped[float | None] = mapped_column(Float, nullable=True, comment="对联营/合营企业投资收益")
    fv_value_chg_gain: Mapped[float | None] = mapped_column(Float, nullable=True, comment="公允价值变动净收益")
    forex_gain: Mapped[float | None] = mapped_column(Float, nullable=True, comment="汇兑净收益")
    oth_income: Mapped[float | None] = mapped_column(Float, nullable=True, comment="其他收益")
    asset_disp_income: Mapped[float | None] = mapped_column(Float, nullable=True, comment="资产处置收益")

    operate_profit: Mapped[float | None] = mapped_column(Float, nullable=True, comment="营业利润")
    non_oper_income: Mapped[float | None] = mapped_column(Float, nullable=True, comment="营业外收入")
    non_oper_exp: Mapped[float | None] = mapped_column(Float, nullable=True, comment="营业外支出")
    nca_disploss: Mapped[float | None] = mapped_column(Float, nullable=True, comment="非流动资产处置净损失")
    total_profit: Mapped[float | None] = mapped_column(Float, nullable=True, comment="利润总额")
    income_tax: Mapped[float | None] = mapped_column(Float, nullable=True, comment="所得税费用")
    n_income: Mapped[float | None] = mapped_column(Float, nullable=True, comment="净利润(含少数股东损益)")
    n_income_attr_p: Mapped[float | None] = mapped_column(Float, nullable=True, comment="净利润(不含少数股东损益)")
    minority_gain: Mapped[float | None] = mapped_column(Float, nullable=True, comment="少数股东损益")

    oth_compr_income: Mapped[float | None] = mapped_column(Float, nullable=True, comment="其他综合收益")
    t_compr_income: Mapped[float | None] = mapped_column(Float, nullable=True, comment="综合收益总额")
    compr_inc_attr_p: Mapped[float | None] = mapped_column(Float, nullable=True, comment="归属母公司综合收益总额")
    compr_inc_attr_m_s: Mapped[float | None] = mapped_column(Float, nullable=True, comment="归属少数股东综合收益总额")

    ebit: Mapped[float | None] = mapped_column(Float, nullable=True, comment="息税前利润")
    ebitda: Mapped[float | None] = mapped_column(Float, nullable=True, comment="息税折旧摊销前利润")
    rd_exp: Mapped[float | None] = mapped_column(Float, nullable=True, comment="研发费用")

    __table_args__ = (
        PrimaryKeyConstraint("symbol", "end_date", "update_flag", name="idx_is_symbol_end_date_update_flag"),
        {"comment": "利润表 - 存储上市公司利润表数据"},
    )
