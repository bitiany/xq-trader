"""B3 成长因子 — 成长性指标。

数据来源：
  - q_or_yoy/q_netprofit_yoy/q_dtprofit_yoy/q_op_yoy/q_ocf_yoy/q_roe_yoy:
    sdc_financial_indicator（季频原始值，前向填充由 CrossSectionReader 完成），同比增长率
  - q_netprofitgrow_qoq/q_orgrow_qoq/q_opgrow_qoq/q_roegrow_qoq:
    sdc_financial_indicator（季频原始值，前向填充由 CrossSectionReader 完成），环比增长率

参照 Barra 风格因子体系与业界成熟框架：
  - 同比增长因子：衡量长期成长趋势
  - 环比增长因子：衡量短期边际变化
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from xqtrader.domain.factor.base import FactorPlugin

# 季频财务因子数据起始日期（sdc_financial_indicator 自 2012-08-24 起有数据）
_FINANCIAL_DATA_START = date(2012, 8, 24)
# 部分同比/环比因子自 2019-04-29 起有数据（数据源补充字段）
_GROWTH_QOQ_DATA_START = date(2019, 4, 29)
# q_or_yoy 自 2019-10-31 起有数据
_Q_OR_YOY_DATA_START = date(2019, 10, 31)
# q_roe_yoy 自 2013-08-21 起有数据
_Q_ROE_YOY_DATA_START = date(2013, 8, 21)
# q_roegrow_qoq 自 2012-10-31 起有数据
_Q_ROEGROW_QOQ_DATA_START = date(2012, 10, 31)


class QOrYoyFactor(FactorPlugin):
    """营收同比增长因子 — 直接取值。"""

    factor_id: str = "q_or_yoy"
    display_name: str = "营收同比增长"
    category: str = "fundamental"
    group_id: str = "q_or_yoy"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["q_or_yoy"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _Q_OR_YOY_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class QNetprofitYoyFactor(FactorPlugin):
    """净利润同比增长因子 — 直接取值。"""

    factor_id: str = "q_netprofit_yoy"
    display_name: str = "净利润同比增长"
    category: str = "fundamental"
    group_id: str = "q_netprofit_yoy"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["q_netprofit_yoy"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class QDtprofitYoyFactor(FactorPlugin):
    """扣非净利润同比增长因子 — 直接取值。"""

    factor_id: str = "q_dtprofit_yoy"
    display_name: str = "扣非净利润同比增长"
    category: str = "fundamental"
    group_id: str = "q_dtprofit_yoy"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["q_dtprofit_yoy"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class QOpYoyFactor(FactorPlugin):
    """营业利润同比增长因子 — 直接取值。"""

    factor_id: str = "q_op_yoy"
    display_name: str = "营业利润同比增长"
    category: str = "fundamental"
    group_id: str = "q_op_yoy"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["q_op_yoy"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class QOcfYoyFactor(FactorPlugin):
    """经营现金流同比增长因子 — 直接取值。"""

    factor_id: str = "q_ocf_yoy"
    display_name: str = "经营现金流同比增长"
    category: str = "fundamental"
    group_id: str = "q_ocf_yoy"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["q_ocf_yoy"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class QRoeYoyFactor(FactorPlugin):
    """ROE同比增长因子 — 直接取值。"""

    factor_id: str = "q_roe_yoy"
    display_name: str = "ROE同比增长"
    category: str = "fundamental"
    group_id: str = "q_roe_yoy"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["q_roe_yoy"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _Q_ROE_YOY_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class QNetprofitgrowQoqFactor(FactorPlugin):
    """净利润环比增长因子 — 直接取值。"""

    factor_id: str = "q_netprofitgrow_qoq"
    display_name: str = "净利润环比增长"
    category: str = "fundamental"
    group_id: str = "q_netprofitgrow_qoq"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["q_netprofitgrow_qoq"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _GROWTH_QOQ_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class QOrgrowQoqFactor(FactorPlugin):
    """营收环比增长因子 — 直接取值。"""

    factor_id: str = "q_orgrow_qoq"
    display_name: str = "营收环比增长"
    category: str = "fundamental"
    group_id: str = "q_orgrow_qoq"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["q_orgrow_qoq"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _GROWTH_QOQ_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class QOpgrowQoqFactor(FactorPlugin):
    """营业利润环比增长因子 — 直接取值。"""

    factor_id: str = "q_opgrow_qoq"
    display_name: str = "营业利润环比增长"
    category: str = "fundamental"
    group_id: str = "q_opgrow_qoq"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["q_opgrow_qoq"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _GROWTH_QOQ_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class QRoegrowQoqFactor(FactorPlugin):
    """ROE环比增长因子 — 直接取值。"""

    factor_id: str = "q_roegrow_qoq"
    display_name: str = "ROE环比增长"
    category: str = "fundamental"
    group_id: str = "q_roegrow_qoq"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["q_roegrow_qoq"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _Q_ROEGROW_QOQ_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class DtNetprofitYoyFactor(FactorPlugin):
    """年度扣非净利润同比增长因子 — 直接取值。

    与单季度同比（q_dtprofit_yoy）互补，反映长期成长趋势。
    """

    factor_id: str = "dt_netprofit_yoy"
    display_name: str = "年度扣非净利润同比"
    category: str = "fundamental"
    group_id: str = "dt_netprofit_yoy"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["dt_netprofit_yoy"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class EquityYoyFactor(FactorPlugin):
    """净资产同比增长因子 — 直接取值。

    衡量企业规模扩张速度，与盈利增长配合验证成长质量。
    """

    factor_id: str = "equity_yoy"
    display_name: str = "净资产同比"
    category: str = "fundamental"
    group_id: str = "equity_yoy"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["equity_yoy"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class AssetsYoyFactor(FactorPlugin):
    """总资产同比增长因子 — 直接取值。

    衡量企业资产规模扩张速度，反映外延式成长能力。
    """

    factor_id: str = "assets_yoy"
    display_name: str = "总资产同比"
    category: str = "fundamental"
    group_id: str = "assets_yoy"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["assets_yoy"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)
