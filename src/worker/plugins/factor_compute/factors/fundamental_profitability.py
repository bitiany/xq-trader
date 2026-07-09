"""B2 盈利因子 — 盈利能力指标。

数据来源：
  - roe/roe_waa/roe_dt/roa/roic/grossprofit_margin/netprofit_margin:
    sdc_financial_indicator（季频原始值，前向填充由 CrossSectionReader 完成）
  - gp_to_assets: 由 grossprofit_margin × assets_turn 计算得出

参照 Barra 风格因子体系与业界成熟框架：
  - roe: 净资产收益率，盈利因子核心
  - roe_waa: 加权平均ROE，盈利因子核心
  - roe_dt: ROE扣非，盈利因子核心
  - roa: 总资产报酬率，盈利因子辅助
  - roic: 投入资本回报率，盈利因子辅助
  - grossprofit_margin: 销售毛利率，盈利因子辅助
  - netprofit_margin: 销售净利率，盈利因子辅助
  - gp_to_assets: 资产毛利率 = 毛利率 × 周转率，杜邦分解衍生
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from xqtrader.domain.factor.base import FactorPlugin

# 季频财务因子数据起始日期（sdc_financial_indicator 自 2012-08-24 起有数据）
_FINANCIAL_DATA_START = date(2012, 8, 24)


class RoeFactor(FactorPlugin):
    """净资产收益率因子 — 直接取值。"""

    factor_id: str = "roe"
    display_name: str = "净资产收益率"
    category: str = "fundamental"
    group_id: str = "roe"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["roe"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class RoeWaaFactor(FactorPlugin):
    """加权平均ROE因子 — 直接取值。"""

    factor_id: str = "roe_waa"
    display_name: str = "加权平均ROE"
    category: str = "fundamental"
    group_id: str = "roe_waa"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["roe_waa"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class RoeDtFactor(FactorPlugin):
    """ROE扣非因子 — 直接取值。"""

    factor_id: str = "roe_dt"
    display_name: str = "ROE扣非"
    category: str = "fundamental"
    group_id: str = "roe_dt"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["roe_dt"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class RoaFactor(FactorPlugin):
    """总资产报酬率因子 — 直接取值。"""

    factor_id: str = "roa"
    display_name: str = "总资产报酬率"
    category: str = "fundamental"
    group_id: str = "roa"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["roa"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class RoicFactor(FactorPlugin):
    """投入资本回报率因子 — 直接取值。"""

    factor_id: str = "roic"
    display_name: str = "投入资本回报率"
    category: str = "fundamental"
    group_id: str = "roic"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["roic"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class GrossprofitMarginFactor(FactorPlugin):
    """销售毛利率因子 — 直接取值。"""

    factor_id: str = "grossprofit_margin"
    display_name: str = "销售毛利率"
    category: str = "fundamental"
    group_id: str = "grossprofit_margin"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["grossprofit_margin"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class NetprofitMarginFactor(FactorPlugin):
    """销售净利率因子 — 直接取值。"""

    factor_id: str = "netprofit_margin"
    display_name: str = "销售净利率"
    category: str = "fundamental"
    group_id: str = "netprofit_margin"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["netprofit_margin"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class GpToAssetsFactor(FactorPlugin):
    """资产毛利率因子 — 毛利率 × 周转率 = 资产毛利率。

    杜邦分解衍生指标：资产毛利率 = 销售毛利率 × 总资产周转率，
    综合反映盈利能力与运营效率。
    """

    factor_id: str = "gp_to_assets"
    display_name: str = "资产毛利率"
    category: str = "fundamental"
    group_id: str = "gp_to_assets"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["grossprofit_margin", "assets_turn"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        grossprofit_margin = df["grossprofit_margin"].astype(float)
        assets_turn = df["assets_turn"].astype(float)
        result = np.where(
            (grossprofit_margin.notna()) & (assets_turn.notna()),
            grossprofit_margin * assets_turn,
            np.nan,
        )
        return pd.DataFrame({self.factor_id: result}, index=df.index)


class OpOfGrFactor(FactorPlugin):
    """营业利润率因子 — 营业利润/营业总收入，直接取值。"""

    factor_id: str = "op_of_gr"
    display_name: str = "营业利润率"
    category: str = "fundamental"
    group_id: str = "op_of_gr"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["op_of_gr"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class EbitOfGrFactor(FactorPlugin):
    """EBIT利润率因子 — 息税前利润/营业总收入，直接取值。"""

    factor_id: str = "ebit_of_gr"
    display_name: str = "EBIT利润率"
    category: str = "fundamental"
    group_id: str = "ebit_of_gr"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["ebit_of_gr"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class ExpenseOfSalesFactor(FactorPlugin):
    """期间费用率因子 — 销售期间费用率，直接取值。

    方向 ASC：期间费用率越低，成本控制能力越强，盈利质量越高。
    """

    factor_id: str = "expense_of_sales"
    display_name: str = "期间费用率"
    category: str = "fundamental"
    group_id: str = "expense_of_sales"
    direction: str = "ASC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["expense_of_sales"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)
