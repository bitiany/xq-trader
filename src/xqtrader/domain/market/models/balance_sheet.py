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
class BalanceSheet(Base):
    """资产负债表 - 存储上市公司资产负债表数据"""

    __bind_key__ = "stock"
    __tablename__ = "sdc_balance_sheet"

    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True, comment="TS股票代码")
    ann_date: Mapped[str | None] = mapped_column(Date, nullable=True, index=True, comment="公告日期")
    f_ann_date: Mapped[str | None] = mapped_column(Date, nullable=True, comment="实际公告日期")
    end_date: Mapped[Date] = mapped_column(Date, nullable=False, index=True, comment="报告期")
    report_type: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="报表类型")
    comp_type: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="公司类型(1一般工商业2银行3保险4证券)")
    end_type: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="报告期类型")
    update_flag: Mapped[str | None] = mapped_column(String(1), nullable=True, comment="更新标识(1最新)")

    total_share: Mapped[float | None] = mapped_column(Float, nullable=True, comment="期末总股本")
    cap_rese: Mapped[float | None] = mapped_column(Float, nullable=True, comment="资本公积金")
    undistr_porfit: Mapped[float | None] = mapped_column(Float, nullable=True, comment="未分配利润")
    surplus_rese: Mapped[float | None] = mapped_column(Float, nullable=True, comment="盈余公积金")
    special_rese: Mapped[float | None] = mapped_column(Float, nullable=True, comment="专项储备")
    money_cap: Mapped[float | None] = mapped_column(Float, nullable=True, comment="货币资金")
    trad_asset: Mapped[float | None] = mapped_column(Float, nullable=True, comment="交易性金融资产")
    notes_receiv: Mapped[float | None] = mapped_column(Float, nullable=True, comment="应收票据")
    accounts_receiv: Mapped[float | None] = mapped_column(Float, nullable=True, comment="应收账款")
    oth_receiv: Mapped[float | None] = mapped_column(Float, nullable=True, comment="其他应收款")
    prepayment: Mapped[float | None] = mapped_column(Float, nullable=True, comment="预付款项")
    div_receiv: Mapped[float | None] = mapped_column(Float, nullable=True, comment="应收股利")
    int_receiv: Mapped[float | None] = mapped_column(Float, nullable=True, comment="应收利息")
    inventories: Mapped[float | None] = mapped_column(Float, nullable=True, comment="存货")
    amor_exp: Mapped[float | None] = mapped_column(Float, nullable=True, comment="待摊费用")
    nca_within_1y: Mapped[float | None] = mapped_column(Float, nullable=True, comment="一年内到期的非流动资产")
    total_cur_assets: Mapped[float | None] = mapped_column(Float, nullable=True, comment="流动资产合计")
    fa_avail_for_sale: Mapped[float | None] = mapped_column(Float, nullable=True, comment="可供出售金融资产")
    htm_invest: Mapped[float | None] = mapped_column(Float, nullable=True, comment="持有至到期投资")
    lt_eqt_invest: Mapped[float | None] = mapped_column(Float, nullable=True, comment="长期股权投资")
    invest_real_estate: Mapped[float | None] = mapped_column(Float, nullable=True, comment="投资性房地产")
    time_deposits: Mapped[float | None] = mapped_column(Float, nullable=True, comment="定期存款")
    oth_assets: Mapped[float | None] = mapped_column(Float, nullable=True, comment="其他资产")
    lt_rec: Mapped[float | None] = mapped_column(Float, nullable=True, comment="长期应收款")
    fix_assets: Mapped[float | None] = mapped_column(Float, nullable=True, comment="固定资产")
    cip: Mapped[float | None] = mapped_column(Float, nullable=True, comment="在建工程")
    const_materials: Mapped[float | None] = mapped_column(Float, nullable=True, comment="工程物资")
    fixed_assets_disp: Mapped[float | None] = mapped_column(Float, nullable=True, comment="固定资产清理")
    intan_assets: Mapped[float | None] = mapped_column(Float, nullable=True, comment="无形资产")
    r_and_d: Mapped[float | None] = mapped_column(Float, nullable=True, comment="研发支出")
    goodwill: Mapped[float | None] = mapped_column(Float, nullable=True, comment="商誉")
    lt_amor_exp: Mapped[float | None] = mapped_column(Float, nullable=True, comment="长期待摊费用")
    defer_tax_assets: Mapped[float | None] = mapped_column(Float, nullable=True, comment="递延所得税资产")
    oth_nca: Mapped[float | None] = mapped_column(Float, nullable=True, comment="其他非流动资产")
    total_nca: Mapped[float | None] = mapped_column(Float, nullable=True, comment="非流动资产合计")
    total_assets: Mapped[float | None] = mapped_column(Float, nullable=True, comment="资产总计")

    lt_borr: Mapped[float | None] = mapped_column(Float, nullable=True, comment="长期借款")
    st_borr: Mapped[float | None] = mapped_column(Float, nullable=True, comment="短期借款")
    trading_fl: Mapped[float | None] = mapped_column(Float, nullable=True, comment="交易性金融负债")
    notes_payable: Mapped[float | None] = mapped_column(Float, nullable=True, comment="应付票据")
    acct_payable: Mapped[float | None] = mapped_column(Float, nullable=True, comment="应付账款")
    adv_receipts: Mapped[float | None] = mapped_column(Float, nullable=True, comment="预收款项")
    payroll_payable: Mapped[float | None] = mapped_column(Float, nullable=True, comment="应付职工薪酬")
    taxes_payable: Mapped[float | None] = mapped_column(Float, nullable=True, comment="应交税费")
    int_payable: Mapped[float | None] = mapped_column(Float, nullable=True, comment="应付利息")
    div_payable: Mapped[float | None] = mapped_column(Float, nullable=True, comment="应付股利")
    oth_payable: Mapped[float | None] = mapped_column(Float, nullable=True, comment="其他应付款")
    non_cur_liab_due_1y: Mapped[float | None] = mapped_column(Float, nullable=True, comment="一年内到期的非流动负债")
    oth_cur_liab: Mapped[float | None] = mapped_column(Float, nullable=True, comment="其他流动负债")
    total_cur_liab: Mapped[float | None] = mapped_column(Float, nullable=True, comment="流动负债合计")
    bond_payable: Mapped[float | None] = mapped_column(Float, nullable=True, comment="应付债券")
    lt_payable: Mapped[float | None] = mapped_column(Float, nullable=True, comment="长期应付款")
    specific_payables: Mapped[float | None] = mapped_column(Float, nullable=True, comment="专项应付款")
    estimated_liab: Mapped[float | None] = mapped_column(Float, nullable=True, comment="预计负债")
    defer_tax_liab: Mapped[float | None] = mapped_column(Float, nullable=True, comment="递延所得税负债")
    oth_ncl: Mapped[float | None] = mapped_column(Float, nullable=True, comment="其他非流动负债")
    total_ncl: Mapped[float | None] = mapped_column(Float, nullable=True, comment="非流动负债合计")
    oth_liab: Mapped[float | None] = mapped_column(Float, nullable=True, comment="其他负债")
    total_liab: Mapped[float | None] = mapped_column(Float, nullable=True, comment="负债合计")

    treasury_share: Mapped[float | None] = mapped_column(Float, nullable=True, comment="库存股")
    ordin_risk_reser: Mapped[float | None] = mapped_column(Float, nullable=True, comment="一般风险准备")
    forex_differ: Mapped[float | None] = mapped_column(Float, nullable=True, comment="外币报表折算差额")
    invest_loss_unconf: Mapped[float | None] = mapped_column(Float, nullable=True, comment="未确认投资损失")
    minority_int: Mapped[float | None] = mapped_column(Float, nullable=True, comment="少数股东权益")
    total_hldr_eqy_exc_min_int: Mapped[float | None] = mapped_column(Float, nullable=True, comment="归属母公司股东权益合计")
    total_hldr_eqy_inc_min_int: Mapped[float | None] = mapped_column(Float, nullable=True, comment="股东权益合计(含少数股东权益)")
    total_liab_hldr_eqy: Mapped[float | None] = mapped_column(Float, nullable=True, comment="负债及股东权益合计")

    __table_args__ = (
        PrimaryKeyConstraint("symbol", "end_date",'update_flag', name="idx_bs_symbol_end_date_update_flag"),
        {"comment": "资产负债表 - 存储上市公司资产负债表数据"},
    )
