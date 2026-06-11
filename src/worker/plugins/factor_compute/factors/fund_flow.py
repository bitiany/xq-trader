"""资金流因子 — 占比形式，截面可比。

参照 factor-catalog v5.0 "变化优先"原则：
  - 资金流绝对金额无截面可比性（大盘股天然流入大），改为占比形式
  - FundFlowIndividual 已提供 huge_net_pct / big_net_pct / main_net_pct 字段
  - 全部净流入占比需计算：net_mf_amt / amount

因子ID：
  - cs_main_net_pct: 主力净流入占比（截面直取，数据源已有）
  - cs_net_mf_pct: 全部净流入占比（net_mf_amt / amount）
  - huge_net_pct: 超大单净流入占比（数据源已有）
  - big_net_pct: 大单净流入占比（数据源已有）

依赖资金流数据（FundFlowIndividual），通过 load_stage 合并到行情 DataFrame。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from xqtrader.domain.factor.base import FactorPlugin


class CsMainNetPctFactor(FactorPlugin):
    """主力净流入占比因子 — 数据源直接提供，截面可比。"""

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


class CsNetMfPctFactor(FactorPlugin):
    """全部净流入占比因子 — net_mf_amt / amount × 100，截面可比。

    替代原 cs_net_mf_amt（绝对金额无截面可比性）。
    """

    factor_id: str = "cs_net_mf_pct"
    display_name: str = "全部净流入占比"
    category: str = "fund_flow"
    group_id: str = "cs_net_mf_pct"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["net_mf_amt", "amount"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fund_flow"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        net_mf_amt = df["net_mf_amt"].astype(float)
        amount = df["amount"].astype(float)
        pct = np.where(amount != 0, net_mf_amt / amount * 100, np.nan)
        return pd.DataFrame({self.factor_id: pct}, index=df.index)


class HugeNetPctFactor(FactorPlugin):
    """超大单净流入占比因子 — 数据源直接提供，截面可比。

    替代原 huge_net_amt（绝对金额无截面可比性）。
    """

    factor_id: str = "huge_net_pct"
    display_name: str = "超大单净流入占比"
    category: str = "fund_flow"
    group_id: str = "huge_net_pct"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["huge_net_pct"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fund_flow"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        values = df["huge_net_pct"].astype(float)
        return pd.DataFrame({self.factor_id: values.values}, index=df.index)


class BigNetPctFactor(FactorPlugin):
    """大单净流入占比因子 — 数据源直接提供，截面可比。

    替代原 big_net_amt（绝对金额无截面可比性）。
    """

    factor_id: str = "big_net_pct"
    display_name: str = "大单净流入占比"
    category: str = "fund_flow"
    group_id: str = "big_net_pct"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["big_net_pct"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fund_flow"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        values = df["big_net_pct"].astype(float)
        return pd.DataFrame({self.factor_id: values.values}, index=df.index)
