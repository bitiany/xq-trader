"""B5 杠杆因子 — 资本结构与偿债能力指标。

数据来源：
  - debt_to_assets/current_ratio/eqt_to_talcapital/ebit_to_interest/ocf_to_debt:
    sdc_financial_indicator（季频原始值，前向填充由 CrossSectionReader 完成），杠杆与偿债指标
  - mlev: 由 debt_to_assets × assets_to_eqt 计算得出（D/E 比率近似，非市场杠杆）

参照 Barra 风格因子体系与业界成熟框架：
  - 资产负债率：方向 ASC（负债率越低风险越小）
  - 流动比率/利息保障倍数/现金流负债比：方向 DESC（越高偿债能力越强）
  - 市场杠杆：方向 ASC（杠杆越低风险越小）
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from xqtrader.domain.factor.base import FactorPlugin

# 季频财务因子数据起始日期（sdc_financial_indicator 自 2012-08-24 起有数据）
_FINANCIAL_DATA_START = date(2012, 8, 24)
# ebit_to_interest 自 2018-08-31 起有数据（数据源补充字段）
_EBIT_TO_INTEREST_DATA_START = date(2018, 8, 31)


class DebtToAssetsFactor(FactorPlugin):
    """资产负债率因子 — 直接取值。"""

    factor_id: str = "debt_to_assets"
    display_name: str = "资产负债率"
    category: str = "fundamental"
    group_id: str = "debt_to_assets"
    direction: str = "ASC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["debt_to_assets"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class CurrentRatioFactor(FactorPlugin):
    """流动比率因子 — 直接取值。"""

    factor_id: str = "current_ratio"
    display_name: str = "流动比率"
    category: str = "fundamental"
    group_id: str = "current_ratio"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["current_ratio"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class EqtToTalcapitalFactor(FactorPlugin):
    """权益投入资本比因子 — 直接取值。"""

    factor_id: str = "eqt_to_talcapital"
    display_name: str = "权益投入资本比"
    category: str = "fundamental"
    group_id: str = "eqt_to_talcapital"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["eqt_to_talcapital"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class EbitToInterestFactor(FactorPlugin):
    """利息保障倍数因子 — 直接取值。"""

    factor_id: str = "ebit_to_interest"
    display_name: str = "利息保障倍数"
    category: str = "fundamental"
    group_id: str = "ebit_to_interest"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["ebit_to_interest"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _EBIT_TO_INTEREST_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class OcfToDebtFactor(FactorPlugin):
    """经营现金流负债比因子 — 直接取值。"""

    factor_id: str = "ocf_to_debt"
    display_name: str = "经营现金流负债比"
    category: str = "fundamental"
    group_id: str = "ocf_to_debt"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["ocf_to_debt"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class MlevFactor(FactorPlugin):
    """杠杆因子(D/E) — 资产负债率 × 权益乘数。

    近似计算：D/E = debt_to_assets × assets_to_eqt（资产负债率 × 权益乘数 = 债务/权益）。
    注：因子目录定义 mlev 为"市场杠杆 = (总市值+优先股+长债)/总市值"，
    当前使用 D/E 比率近似，需在因子目录中同步标注。
    方向 ASC：杠杆越低风险越小。
    """

    factor_id: str = "mlev"
    display_name: str = "杠杆因子(D/E)"
    category: str = "fundamental"
    group_id: str = "mlev"
    direction: str = "ASC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["debt_to_assets", "assets_to_eqt"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        debt_to_assets = df["debt_to_assets"].astype(float)
        assets_to_eqt = df["assets_to_eqt"].astype(float)
        result = np.where(
            (debt_to_assets.notna()) & (assets_to_eqt.notna()),
            debt_to_assets * assets_to_eqt,
            np.nan,
        )
        return pd.DataFrame({self.factor_id: result}, index=df.index)


class QuickRatioFactor(FactorPlugin):
    """速动比率因子 — 直接取值。

    衡量短期偿债能力（剔除存货），业界主流平台必备指标。
    """

    factor_id: str = "quick_ratio"
    display_name: str = "速动比率"
    category: str = "fundamental"
    group_id: str = "quick_ratio"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["quick_ratio"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class CashRatioFactor(FactorPlugin):
    """保守速动比率因子 — 直接取值。

    衡量极端保守的短期偿债能力（仅货币资金+短期投资）。
    """

    factor_id: str = "cash_ratio"
    display_name: str = "保守速动比率"
    category: str = "fundamental"
    group_id: str = "cash_ratio"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["cash_ratio"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class DebtToEqtFactor(FactorPlugin):
    """产权比率因子 — 总负债/股东权益，直接取值。

    衡量资本结构，业界主流平台核心指标。
    方向 ASC：产权比率越高，财务风险越大。
    """

    factor_id: str = "debt_to_eqt"
    display_name: str = "产权比率"
    category: str = "fundamental"
    group_id: str = "debt_to_eqt"
    direction: str = "ASC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["debt_to_eqt"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class AssetsToEqtFactor(FactorPlugin):
    """权益乘数因子 — 总资产/股东权益，直接取值。

    杜邦分析核心指标，衡量财务杠杆水平。
    方向 ASC：权益乘数越高，财务杠杆越大。
    """

    factor_id: str = "assets_to_eqt"
    display_name: str = "权益乘数"
    category: str = "fundamental"
    group_id: str = "assets_to_eqt"
    direction: str = "ASC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["assets_to_eqt"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class EbitdaToDebtFactor(FactorPlugin):
    """EBITDA/负债因子 — 直接取值。

    国际通用偿债能力指标，衡量企业偿债能力。
    """

    factor_id: str = "ebitda_to_debt"
    display_name: str = "EBITDA/负债"
    category: str = "fundamental"
    group_id: str = "ebitda_to_debt"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["ebitda_to_debt"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class IntToTalcapFactor(FactorPlugin):
    """带息债务/投入资本因子 — 直接取值。

    衡量资本结构中的有息负债占比。
    方向 ASC：带息债务占比越高，财务成本压力越大。
    """

    factor_id: str = "int_to_talcap"
    display_name: str = "带息债务/投入资本"
    category: str = "fundamental"
    group_id: str = "int_to_talcap"
    direction: str = "ASC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["int_to_talcap"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class TangibleassetToDebtFactor(FactorPlugin):
    """有形资产/负债因子 — 直接取值。

    衡量资产对负债的保障程度，剔除无形资产后的真实偿债能力。
    """

    factor_id: str = "tangibleasset_to_debt"
    display_name: str = "有形资产/负债"
    category: str = "fundamental"
    group_id: str = "tangibleasset_to_debt"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["tangibleasset_to_debt"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class OcfToShortdebtFactor(FactorPlugin):
    """经营现金流/流动负债因子 — 直接取值。

    衡量短期偿债能力（现金流视角），补充流动比率不足。
    """

    factor_id: str = "ocf_to_shortdebt"
    display_name: str = "经营现金流/流动负债"
    category: str = "fundamental"
    group_id: str = "ocf_to_shortdebt"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["ocf_to_shortdebt"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class OcfToInterestdebtFactor(FactorPlugin):
    """经营现金流/带息债务因子 — 直接取值。

    衡量有息负债的现金流覆盖能力，国际通用偿债指标。
    """

    factor_id: str = "ocf_to_interestdebt"
    display_name: str = "经营现金流/带息债务"
    category: str = "fundamental"
    group_id: str = "ocf_to_interestdebt"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["ocf_to_interestdebt"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)


class OcfToNetdebtFactor(FactorPlugin):
    """经营现金流/净债务因子 — 直接取值。

    衡量净债务的现金流覆盖能力，剔除现金后的真实债务压力。
    """

    factor_id: str = "ocf_to_netdebt"
    display_name: str = "经营现金流/净债务"
    category: str = "fundamental"
    group_id: str = "ocf_to_netdebt"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["ocf_to_netdebt"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fina_indicator"
    data_start_date: date = _FINANCIAL_DATA_START
    update_freq: str = "quarterly"
    report_lag_days: int = 120

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({self.factor_id: df[self.dependencies[0]].astype(float)}, index=df.index)
