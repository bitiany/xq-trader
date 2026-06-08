"""现金流量表 ORM 模型。"""

# ruff: noqa: E501

from datetime import date

from sqlalchemy import Date, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base


class CashFlowStatement(Base):
    """现金流量表"""

    __bind_key__ = "stock"
    __tablename__ = "sdc_cash_flow"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True, comment="TS股票代码")
    ann_date: Mapped[date | None] = mapped_column(Date, comment="公告日期")
    f_ann_date: Mapped[date | None] = mapped_column(Date, comment="实际公告日期")
    end_date: Mapped[date] = mapped_column(Date, primary_key=True, comment="报告期")
    comp_type: Mapped[str | None] = mapped_column(String(10), comment="公司类型(1一般工商业2银行3保险4证券)")
    report_type: Mapped[str | None] = mapped_column(String(10), comment="报表类型")
    end_type: Mapped[str | None] = mapped_column(String(10), comment="报告期类型")
    update_flag: Mapped[str] = mapped_column(String(1), primary_key=True, comment="更新标识(1最新)")
    net_profit: Mapped[float | None] = mapped_column(Float, comment="净利润")
    c_fr_sale_sg: Mapped[float | None] = mapped_column(Float, comment="销售商品提供劳务收到的现金")
    recp_tax_rends: Mapped[float | None] = mapped_column(Float, comment="收到的税费返还")
    n_depos_incr_fi: Mapped[float | None] = mapped_column(Float, comment="客户存款和同业存放款项净增加额")
    c_inf_fr_operate_a: Mapped[float | None] = mapped_column(Float, comment="经营活动现金流入小计")
    c_paid_goods_s: Mapped[float | None] = mapped_column(Float, comment="购买商品接受劳务支付的现金")
    c_paid_to_for_empl: Mapped[float | None] = mapped_column(Float, comment="支付给职工以及为职工支付的现金")
    c_paid_for_taxes: Mapped[float | None] = mapped_column(Float, comment="支付的各项税费")
    oth_cash_pay_oper_act: Mapped[float | None] = mapped_column(Float, comment="支付其他与经营活动有关的现金")
    st_cash_out_act: Mapped[float | None] = mapped_column(Float, comment="经营活动现金流出小计")
    n_cashflow_act: Mapped[float | None] = mapped_column(Float, comment="经营活动产生的现金流量净额")
    c_disp_withdrwl_invest: Mapped[float | None] = mapped_column(Float, comment="收回投资收到的现金")
    c_recp_return_invest: Mapped[float | None] = mapped_column(Float, comment="取得投资收益收到的现金")
    n_recp_disp_fiolta: Mapped[float | None] = mapped_column(Float, comment="处置固定资产无形资产和其他长期资产收回的现金净额")
    stot_inflows_inv_act: Mapped[float | None] = mapped_column(Float, comment="投资活动现金流入小计")
    c_pay_acq_const_fiolta: Mapped[float | None] = mapped_column(Float, comment="购建固定资产无形资产和其他长期资产支付的现金")
    c_paid_invest: Mapped[float | None] = mapped_column(Float, comment="投资支付的现金")
    n_disp_subs_oth_biz: Mapped[float | None] = mapped_column(Float, comment="取得子公司及其他营业单位支付的现金净额")
    oth_pay_ral_inv_act: Mapped[float | None] = mapped_column(Float, comment="支付其他与投资活动有关的现金")
    n_incr_pledge_loan: Mapped[float | None] = mapped_column(Float, comment="质押贷款净增加额")
    stot_out_inv_act: Mapped[float | None] = mapped_column(Float, comment="投资活动现金流出小计")
    n_cashflow_inv_act: Mapped[float | None] = mapped_column(Float, comment="投资活动产生的现金流量净额")
    c_recp_borrow: Mapped[float | None] = mapped_column(Float, comment="取得借款收到的现金")
    proc_issue_bonds: Mapped[float | None] = mapped_column(Float, comment="发行债券收到的现金")
    oth_cash_recp_ral_fnc_act: Mapped[float | None] = mapped_column(Float, comment="收到其他与筹资活动有关的现金")
    stot_cash_in_fnc_act: Mapped[float | None] = mapped_column(Float, comment="筹资活动现金流入小计")
    free_cashflow: Mapped[float | None] = mapped_column(Float, comment="企业自由现金流量")
    c_prepay_amt_borr: Mapped[float | None] = mapped_column(Float, comment="偿还债务支付的现金")
    c_pay_dist_dpcp_int_exp: Mapped[float | None] = mapped_column(Float, comment="分配股利利润或偿付利息支付的现金")
    incl_dvd_profit_paid_sc_ms: Mapped[float | None] = mapped_column(Float, comment="其中子公司支付给少数股东的股利利润")
    oth_cashpay_ral_fnc_act: Mapped[float | None] = mapped_column(Float, comment="支付其他与筹资活动有关的现金")
    stot_cashout_fnc_act: Mapped[float | None] = mapped_column(Float, comment="筹资活动现金流出小计")
    n_cash_flows_fnc_act: Mapped[float | None] = mapped_column(Float, comment="筹资活动产生的现金流量净额")
    eff_fx_flu_cash: Mapped[float | None] = mapped_column(Float, comment="汇率变动对现金的影响")
    n_incr_cash_cash_equ: Mapped[float | None] = mapped_column(Float, comment="现金及现金等价物净增加额")
    c_cash_equ_beg_period: Mapped[float | None] = mapped_column(Float, comment="期初现金及现金等价物余额")
    c_cash_equ_end_period: Mapped[float | None] = mapped_column(Float, comment="期末现金及现金等价物余额")

    __table_args__ = ({"comment": "现金流量表 - 存储上市公司现金流量表数据"},)
