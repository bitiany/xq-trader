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

import numpy as np
import pandas as pd

from xqtrader.domain.factor.base import FactorPlugin


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
