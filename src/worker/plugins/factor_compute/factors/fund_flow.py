"""资金流因子 — CsMainNetPct / HugeNetAmt / BigNetAmt / CsNetMfAmt / MainNetAmt / MainNetAmtMA。

因子ID命名遵循 factor-catalog.md 规范：
  - cs_main_net_pct: 主力净流入占比（截面直取）
  - huge_net_amt: 超大单净流入额
  - big_net_amt: 大单净流入额
  - cs_net_mf_amt: 全部净流入额（截面直取）
  - main_net_amt: 主力净流入额
  - main_net_amt_ma_5: 主力净流入额5日均值

依赖资金流数据（FundFlowIndividual），通过 load_stage 合并到行情 DataFrame。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from xqtrader.domain.factor.base import FactorPlugin


class CsMainNetPctFactor(FactorPlugin):
    """主力净流入占比因子（截面直取）。"""

    factor_id: str = "cs_main_net_pct"
    display_name: str = "主力净流入占比"
    category: str = "fund_flow"
    group_id: str = "cs_main_net_pct"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["main_net_pct"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fund_flow"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        values = df["main_net_pct"].astype(float)
        return pd.DataFrame({self.factor_id: values.values}, index=df.index)


class HugeNetAmtFactor(FactorPlugin):
    """超大单净流入额因子。"""

    factor_id: str = "huge_net_amt"
    display_name: str = "超大单净流入额"
    category: str = "fund_flow"
    group_id: str = "huge_net_amt"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["huge_net_amt"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fund_flow"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        values = df["huge_net_amt"].astype(float)
        return pd.DataFrame({self.factor_id: values.values}, index=df.index)


class BigNetAmtFactor(FactorPlugin):
    """大单净流入额因子。"""

    factor_id: str = "big_net_amt"
    display_name: str = "大单净流入额"
    category: str = "fund_flow"
    group_id: str = "big_net_amt"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["big_net_amt"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fund_flow"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        values = df["big_net_amt"].astype(float)
        return pd.DataFrame({self.factor_id: values.values}, index=df.index)


class CsNetMfAmtFactor(FactorPlugin):
    """全部净流入额因子（截面直取）。"""

    factor_id: str = "cs_net_mf_amt"
    display_name: str = "全部净流入额"
    category: str = "fund_flow"
    group_id: str = "cs_net_mf_amt"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["net_mf_amt"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fund_flow"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        values = df["net_mf_amt"].astype(float)
        return pd.DataFrame({self.factor_id: values.values}, index=df.index)


class MainNetAmtFactor(FactorPlugin):
    """主力净流入额因子。"""

    factor_id: str = "main_net_amt"
    display_name: str = "主力净流入额"
    category: str = "fund_flow"
    group_id: str = "main_net_amt"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["main_net_amt"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fund_flow"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        values = df["main_net_amt"].astype(float)
        return pd.DataFrame({self.factor_id: values.values}, index=df.index)


class MainNetAmtMAFactor(FactorPlugin):
    """主力净流入额均值因子。"""

    factor_id: str = ""
    display_name: str = ""
    category: str = "fund_flow"
    group_id: str = "main_net_amt_ma"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["main_net_amt"]
    min_periods: int = 5
    requires_full_history: bool = False
    data_origin: str = "fund_flow"

    def __init__(self, period: int = 5, **kwargs: Any) -> None:
        self.period = period
        self.factor_id = f"main_net_amt_ma_{period}"
        self.display_name = f"主力净流入额MA({period})"
        self.min_periods = period
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        amt = df["main_net_amt"].astype(float)
        ma = amt.rolling(window=self.period).mean()
        return pd.DataFrame({self.factor_id: ma.values}, index=df.index)
