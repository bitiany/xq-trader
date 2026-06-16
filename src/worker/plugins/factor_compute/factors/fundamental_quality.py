"""B4 质量因子 — 盈利质量与运营效率指标。

数据来源：
  - ocf_to_profit/ocf_to_or/salescash_to_or/dtprofit_to_profit:
    sdc_financial_indicator（季频原始值，前向填充由 CrossSectionReader 完成），盈利质量指标
  - assets_turn/inv_turn/ar_turn:
    sdc_financial_indicator（季频原始值，前向填充由 CrossSectionReader 完成），运营效率指标
  - accra: 由 (netprofit_margin - ocf_to_or) * assets_turn 计算得出

参照 Barra 风格因子体系与业界成熟框架：
  - 现金流质量因子：衡量盈利的现金含量
  - 周转率因子：衡量运营效率
  - 应计利润因子：衡量盈余管理风险，方向 ASC（应计利润越低质量越高）
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from xqtrader.domain.factor.base import FactorPlugin


class OcfToProfitFactor(FactorPlugin):
    """经营现金流净利润比因子 — 直接取值。"""

    factor_id: str = "ocf_to_profit"
    display_name: str = "经营现金流净利润比"
    category: str = "fundamental"
    group_id: str = "ocf_to_profit"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["ocf_to_profit"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class OcfToOrFactor(FactorPlugin):
    """经营现金流营收比因子 — 直接取值。"""

    factor_id: str = "ocf_to_or"
    display_name: str = "经营现金流营收比"
    category: str = "fundamental"
    group_id: str = "ocf_to_or"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["ocf_to_or"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class SalescashToOrFactor(FactorPlugin):
    """销售收现营收比因子 — 直接取值。"""

    factor_id: str = "salescash_to_or"
    display_name: str = "销售收现营收比"
    category: str = "fundamental"
    group_id: str = "salescash_to_or"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["salescash_to_or"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class DtprofitToProfitFactor(FactorPlugin):
    """扣非净利净利润比因子 — 直接取值。"""

    factor_id: str = "dtprofit_to_profit"
    display_name: str = "扣非净利净利润比"
    category: str = "fundamental"
    group_id: str = "dtprofit_to_profit"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["dtprofit_to_profit"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class AssetsTurnFactor(FactorPlugin):
    """总资产周转率因子 — 直接取值。"""

    factor_id: str = "assets_turn"
    display_name: str = "总资产周转率"
    category: str = "fundamental"
    group_id: str = "assets_turn"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["assets_turn"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class InvTurnFactor(FactorPlugin):
    """存货周转率因子 — 直接取值。"""

    factor_id: str = "inv_turn"
    display_name: str = "存货周转率"
    category: str = "fundamental"
    group_id: str = "inv_turn"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["inv_turn"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class ArTurnFactor(FactorPlugin):
    """应收账款周转率因子 — 直接取值。"""

    factor_id: str = "ar_turn"
    display_name: str = "应收账款周转率"
    category: str = "fundamental"
    group_id: str = "ar_turn"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["ar_turn"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class AccraFactor(FactorPlugin):
    """应计利润总资产比因子 — (净利润率 - 经营现金流率) × 周转率。

    近似计算：应计利润/总资产 = (净利润率 - 经营现金流率) × 总资产周转率。
    方向 ASC：应计利润越低，盈余管理风险越小，质量越高。
    """

    factor_id: str = "accra"
    display_name: str = "应计利润总资产比"
    category: str = "fundamental"
    group_id: str = "accra"
    direction: str = "ASC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["netprofit_margin", "ocf_to_or", "assets_turn"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        netprofit_margin = df["netprofit_margin"].astype(float)
        ocf_to_or = df["ocf_to_or"].astype(float)
        assets_turn = df["assets_turn"].astype(float)
        result = np.where(
            (netprofit_margin.notna()) & (ocf_to_or.notna()) & (assets_turn.notna()),
            (netprofit_margin - ocf_to_or) * assets_turn,
            np.nan,
        )
        return pd.DataFrame({self.factor_id: result}, index=df.index)
