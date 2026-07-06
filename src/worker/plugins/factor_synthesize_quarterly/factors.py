"""季频合成因子定义 — 声明式注册，由 factor_synthesize_quarterly 任务产出。

与日频合成因子（factor_synthesize/factors.py）的区别：
  - 输入因子：update_freq=quarterly 的财务因子（B2-B5，32 个）
  - 合成锚点：ann_date（公告日，PIT 依据），非 trade_date
  - 持久化表：fac_financial_composite_value，非 fac_factor_value
  - 评估表：fac_financial_factor_stats，非 fac_factor_stats

合成架构：两阶段分层合成
  第一层：组内等权合成（quality/growth/leverage/efficiency）
          → 独立落库为 composite_quality_quarterly / ... 因子
  第二层：跨组 ICIR 加权合成 → 最终 composite_alpha_quarterly 因子
          ICIR 来源：fac_financial_factor_stats（ann_window=20），无 ICIR 时退化为等权
"""

from __future__ import annotations

import pandas as pd

from xqtrader.domain.factor.base import FactorPlugin

# ── 第一层：组内合成因子 ──


class CompositeQualityQuarterlyFactor(FactorPlugin):
    """质量因子组 — 盈利能力因子等权合成。

    涵盖 ROE/ROA/ROIC 等回报率指标、毛利率/净利率/营业利润率/EBIT利润率等利润率指标、
    期间费用率、应收账款总资产比等资产质量指标。
    """

    factor_id: str = "composite_quality_quarterly"
    display_name: str = "季频质量合成因子"
    category: str = "composite_group"
    direction: str = "DESC"
    description: str = (
        "质量因子组内等权合成"
        "（roe/roe_dt/roe_waa/roa/roic/accra/"
        "grossprofit_margin/netprofit_margin/gp_to_assets/ebit_to_interest/"
        "op_of_gr/ebit_of_gr/expense_of_sales）"
    )
    update_freq: str = "quarterly"
    compute_engine: str = "synthesize"
    is_composite: bool = True
    composite_method: str = "equal_weight"
    composite_factor_ids: list[str] = [
        "roe", "roe_dt", "roe_waa", "roa", "roic", "accra",
        "grossprofit_margin", "netprofit_margin", "gp_to_assets", "ebit_to_interest",
        "op_of_gr", "ebit_of_gr", "expense_of_sales",
    ]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("composite_quality_quarterly 由 factor_synthesize_quarterly 任务合成")


class CompositeGrowthQuarterlyFactor(FactorPlugin):
    """成长因子组 — 同比/环比增长因子等权合成。

    涵盖净利润/扣非净利润/营业利润/营收/经营现金流同比增速、
    净利润/营业利润/营收/ROE 环比增速，以及年度同比增速（扣非净利/净资产/总资产）。
    """

    factor_id: str = "composite_growth_quarterly"
    display_name: str = "季频成长合成因子"
    category: str = "composite_group"
    direction: str = "DESC"
    description: str = (
        "成长因子组内等权合成"
        "（q_netprofit_yoy/q_dtprofit_yoy/q_op_yoy/q_or_yoy/q_ocf_yoy/q_roe_yoy/"
        "q_netprofitgrow_qoq/q_opgrow_qoq/q_orgrow_qoq/q_roegrow_qoq/"
        "dt_netprofit_yoy/equity_yoy/assets_yoy）"
    )
    update_freq: str = "quarterly"
    compute_engine: str = "synthesize"
    is_composite: bool = True
    composite_method: str = "equal_weight"
    composite_factor_ids: list[str] = [
        "q_netprofit_yoy", "q_dtprofit_yoy", "q_op_yoy", "q_or_yoy",
        "q_ocf_yoy", "q_roe_yoy",
        "q_netprofitgrow_qoq", "q_opgrow_qoq", "q_orgrow_qoq", "q_roegrow_qoq",
        "dt_netprofit_yoy", "equity_yoy", "assets_yoy",
    ]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("composite_growth_quarterly 由 factor_synthesize_quarterly 任务合成")


class CompositeLeverageQuarterlyFactor(FactorPlugin):
    """杠杆因子组 — 资产负债/流动性/偿债因子等权合成。

    涵盖资产负债率、产权比率、权益乘数、杠杆因子(D/E)、流动比率、速动比率、
    保守速动比率、利息保障倍数、EBITDA/负债、经营现金流负债比、
    经营现金流流动负债比、经营现金流带息债务比、经营现金流净债务比、
    权益投入资本比、带息债务/投入资本、有形资产/负债。
    """

    factor_id: str = "composite_leverage_quarterly"
    display_name: str = "季频杠杆合成因子"
    category: str = "composite_group"
    direction: str = "DESC"
    description: str = (
        "杠杆因子组内等权合成"
        "（debt_to_assets/mlev/eqt_to_talcapital/current_ratio/ocf_to_debt/"
        "quick_ratio/cash_ratio/debt_to_eqt/assets_to_eqt/ebitda_to_debt/"
        "int_to_talcap/tangibleasset_to_debt/"
        "ocf_to_shortdebt/ocf_to_interestdebt/ocf_to_netdebt）"
    )
    update_freq: str = "quarterly"
    compute_engine: str = "synthesize"
    is_composite: bool = True
    composite_method: str = "equal_weight"
    composite_factor_ids: list[str] = [
        "debt_to_assets", "mlev", "eqt_to_talcapital",
        "current_ratio", "ocf_to_debt",
        "quick_ratio", "cash_ratio", "debt_to_eqt", "assets_to_eqt",
        "ebitda_to_debt", "int_to_talcap", "tangibleasset_to_debt",
        "ocf_to_shortdebt", "ocf_to_interestdebt", "ocf_to_netdebt",
    ]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("composite_leverage_quarterly 由 factor_synthesize_quarterly 任务合成")


class CompositeEfficiencyQuarterlyFactor(FactorPlugin):
    """运营效率+现金流因子组 — 周转率/现金流因子等权合成。

    涵盖应收/存货/总资产/固定资产/流动资产周转率、经营现金流营收比、
    经营现金流净利润比、销售收现营收比、扣非净利润净利润比。
    """

    factor_id: str = "composite_efficiency_quarterly"
    display_name: str = "季频运营效率合成因子"
    category: str = "composite_group"
    direction: str = "DESC"
    description: str = (
        "运营效率+现金流因子组内等权合成"
        "（ar_turn/inv_turn/assets_turn/fa_turn/ca_turn/"
        "ocf_to_or/ocf_to_profit/salescash_to_or/dtprofit_to_profit）"
    )
    update_freq: str = "quarterly"
    compute_engine: str = "synthesize"
    is_composite: bool = True
    composite_method: str = "equal_weight"
    composite_factor_ids: list[str] = [
        "ar_turn", "inv_turn", "assets_turn", "fa_turn", "ca_turn",
        "ocf_to_or", "ocf_to_profit", "salescash_to_or", "dtprofit_to_profit",
    ]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("composite_efficiency_quarterly 由 factor_synthesize_quarterly 任务合成")


# ── 第二层：跨组合成因子 ──


class CompositeAlphaQuarterlyFactor(FactorPlugin):
    """季频最终合成因子 — 组内合成因子跨组 ICIR 加权合成。

    加权方式：从 fac_financial_factor_stats（ann_window=20）读取各组成员的 ICIR，
    取组内 ICIR 均值作为组权重，归一化后加权合成。
    无 ICIR 历史时退化为等权。
    IC/ICIR 是内部加权手段，不体现在因子名称中。
    """

    factor_id: str = "composite_alpha_quarterly"
    display_name: str = "季频综合合成因子"
    category: str = "composite_cross"
    direction: str = "DESC"
    description: str = "跨组ICIR加权合成最终因子（组内合成因子的ICIR加权，退化为等权）"
    update_freq: str = "quarterly"
    compute_engine: str = "synthesize"
    is_composite: bool = True
    composite_method: str = "icir_weight"
    composite_factor_ids: list[str] = [
        "composite_quality_quarterly",
        "composite_growth_quarterly",
        "composite_leverage_quarterly",
        "composite_efficiency_quarterly",
    ]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError("composite_alpha_quarterly 由 factor_synthesize_quarterly 任务合成")
