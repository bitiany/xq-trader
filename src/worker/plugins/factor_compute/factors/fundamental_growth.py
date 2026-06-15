"""B3 成长因子 — 成长性指标。

数据来源：
  - q_or_yoy/q_netprofit_yoy/q_dtprofit_yoy/q_op_yoy/q_ocf_yoy/q_roe_yoy:
    sdc_financial_indicator（前向填充），同比增长率
  - q_netprofitgrow_qoq/q_orgrow_qoq/q_opgrow_qoq/q_roegrow_qoq:
    sdc_financial_indicator（前向填充），环比增长率

参照 Barra 风格因子体系与业界成熟框架：
  - 同比增长因子：衡量长期成长趋势
  - 环比增长因子：衡量短期边际变化
"""

from __future__ import annotations

import pandas as pd

from xqtrader.domain.factor.base import FactorPlugin


class QOrYoyFactor(FactorPlugin):
    """营收同比增长因子 — 直接取值。"""

    factor_id: str = "q_or_yoy"
    display_name: str = "营收同比增长"
    category: str = "fundamental"
    group_id: str = "q_or_yoy"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["q_or_yoy"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "market"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class QNetprofitYoyFactor(FactorPlugin):
    """净利润同比增长因子 — 直接取值。"""

    factor_id: str = "q_netprofit_yoy"
    display_name: str = "净利润同比增长"
    category: str = "fundamental"
    group_id: str = "q_netprofit_yoy"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["q_netprofit_yoy"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "market"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class QDtprofitYoyFactor(FactorPlugin):
    """扣非净利润同比增长因子 — 直接取值。"""

    factor_id: str = "q_dtprofit_yoy"
    display_name: str = "扣非净利润同比增长"
    category: str = "fundamental"
    group_id: str = "q_dtprofit_yoy"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["q_dtprofit_yoy"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "market"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class QOpYoyFactor(FactorPlugin):
    """营业利润同比增长因子 — 直接取值。"""

    factor_id: str = "q_op_yoy"
    display_name: str = "营业利润同比增长"
    category: str = "fundamental"
    group_id: str = "q_op_yoy"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["q_op_yoy"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "market"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class QOcfYoyFactor(FactorPlugin):
    """经营现金流同比增长因子 — 直接取值。"""

    factor_id: str = "q_ocf_yoy"
    display_name: str = "经营现金流同比增长"
    category: str = "fundamental"
    group_id: str = "q_ocf_yoy"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["q_ocf_yoy"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "market"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class QRoeYoyFactor(FactorPlugin):
    """ROE同比增长因子 — 直接取值。"""

    factor_id: str = "q_roe_yoy"
    display_name: str = "ROE同比增长"
    category: str = "fundamental"
    group_id: str = "q_roe_yoy"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["q_roe_yoy"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "market"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class QNetprofitgrowQoqFactor(FactorPlugin):
    """净利润环比增长因子 — 直接取值。"""

    factor_id: str = "q_netprofitgrow_qoq"
    display_name: str = "净利润环比增长"
    category: str = "fundamental"
    group_id: str = "q_netprofitgrow_qoq"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["q_netprofitgrow_qoq"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "market"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class QOrgrowQoqFactor(FactorPlugin):
    """营收环比增长因子 — 直接取值。"""

    factor_id: str = "q_orgrow_qoq"
    display_name: str = "营收环比增长"
    category: str = "fundamental"
    group_id: str = "q_orgrow_qoq"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["q_orgrow_qoq"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "market"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class QOpgrowQoqFactor(FactorPlugin):
    """营业利润环比增长因子 — 直接取值。"""

    factor_id: str = "q_opgrow_qoq"
    display_name: str = "营业利润环比增长"
    category: str = "fundamental"
    group_id: str = "q_opgrow_qoq"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["q_opgrow_qoq"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "market"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class QRoegrowQoqFactor(FactorPlugin):
    """ROE环比增长因子 — 直接取值。"""

    factor_id: str = "q_roegrow_qoq"
    display_name: str = "ROE环比增长"
    category: str = "fundamental"
    group_id: str = "q_roegrow_qoq"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["q_roegrow_qoq"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "market"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)
