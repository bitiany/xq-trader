"""资金流因子 — 占比形式，截面可比。

参照 factor-catalog v5.0 "变化优先"原则：
  - 资金流绝对金额无截面可比性（大盘股天然流入大），改为占比形式
  - FundFlowIndividual 已提供 huge_net_pct / big_net_pct / main_net_pct 字段
  - 全部净流入占比需计算：net_mf_amt / amount

因子ID：
  当日截面（直取/计算）：
  - cs_main_net_pct: 主力净流入占比（截面直取，数据源已有）
  - cs_net_mf_pct: 全部净流入占比（net_mf_amt / amount）
  - huge_net_pct: 超大单净流入占比（数据源已有）
  - big_net_pct: 大单净流入占比（数据源已有）
  - main_small_divergence: 主力-小单行为分化（筹码转移信号）
  - huge_big_divergence: 超大单-大单结构分化（大资金内部结构）

  时序聚合/变化（requires_full_history=True）：
  - main_net_pct_3d: 3日主力净流入占比均值（平滑单日噪音）
  - main_net_pct_5d: 5日主力净流入占比均值（主流多周期统计）
  - main_net_pct_chg: 主力净流入占比变化（资金流加速度）

依赖资金流数据（FundFlowIndividual），通过 load_stage 合并到行情 DataFrame。
DataFrame 按 trade_date 升序排列，适合 rolling/diff 操作。
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from xqtrader.domain.factor.base import FactorPlugin

# moneyflow_dc 数据源自 2023-09-11 起，资金流向因子统一从该日期开始计算
_FUND_FLOW_DATA_START = date(2023, 9, 11)


class CsMainNetPctFactor(FactorPlugin):
    """主力净流入占比因子 — 数据源直接提供，截面可比。"""

    factor_id: str = "cs_main_net_pct"
    display_name: str = "主力净流入占比"
    category: str = "fund_flow"
    group_id: str = "cs_main_net_pct"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["main_net_pct"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fund_flow"
    data_start_date: date = _FUND_FLOW_DATA_START

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
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["net_mf_amt", "amount"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fund_flow"
    data_start_date: date = _FUND_FLOW_DATA_START

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
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["huge_net_pct"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fund_flow"
    data_start_date: date = _FUND_FLOW_DATA_START

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
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["big_net_pct"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fund_flow"
    data_start_date: date = _FUND_FLOW_DATA_START

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        values = df["big_net_pct"].astype(float)
        return pd.DataFrame({self.factor_id: values.values}, index=df.index)


# ── 当日截面衍生因子 ──


class MainSmallDivergenceFactor(FactorPlugin):
    """主力-小单行为分化因子 — 主力净流入占比 - 小单净流入占比。

    经济含义：主力买入 + 散户卖出 = 筹码从散户向主力转移（建仓信号）；
              反之为出货信号。捕捉主力-散户行为背离，单日即可观测。
    数据来源：moneyflow_dc 同时提供 main_net_pct 与 small_net_pct。
    """

    factor_id: str = "main_small_divergence"
    display_name: str = "主力-小单行为分化"
    category: str = "fund_flow"
    group_id: str = "main_small_divergence"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["main_net_pct", "small_net_pct"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fund_flow"
    data_start_date: date = _FUND_FLOW_DATA_START

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        main = df["main_net_pct"].astype(float)
        small = df["small_net_pct"].astype(float)
        divergence = (main - small).values
        return pd.DataFrame({self.factor_id: divergence}, index=df.index)


class HugeBigDivergenceFactor(FactorPlugin):
    """超大单-大单结构分化因子 — 超大单净流入占比 - 大单净流入占比。

    经济含义：反映大资金内部结构。超大单更积极（正值）= 更大资金主导流入；
              大单更积极（负值）= 中大资金主导。捕捉机构资金分层行为。
    数据来源：moneyflow_dc 同时提供 huge_net_pct 与 big_net_pct。
    """

    factor_id: str = "huge_big_divergence"
    display_name: str = "超大单-大单结构分化"
    category: str = "fund_flow"
    group_id: str = "huge_big_divergence"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["huge_net_pct", "big_net_pct"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "fund_flow"
    data_start_date: date = _FUND_FLOW_DATA_START

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        huge = df["huge_net_pct"].astype(float)
        big = df["big_net_pct"].astype(float)
        divergence = (huge - big).values
        return pd.DataFrame({self.factor_id: divergence}, index=df.index)


# ── 时序聚合因子 ──


class MainNetPct3dFactor(FactorPlugin):
    """3日主力净流入占比均值因子 — 平滑单日噪音，反映短期主力持续态度。

    经济含义：单日资金流受主力做T、试探性买卖影响大；
              3日均值能过滤日内噪音，更稳定地反映短期主力态度。
    对标：东方财富/同花顺均提供 3日主力资金净流入统计。
    """

    factor_id: str = "main_net_pct_3d"
    display_name: str = "3日主力净流入占比均值"
    category: str = "fund_flow"
    group_id: str = "main_net_pct_3d"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["main_net_pct"]
    min_periods: int = 3
    requires_full_history: bool = True
    data_origin: str = "fund_flow"
    data_start_date: date = _FUND_FLOW_DATA_START

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        values = df["main_net_pct"].astype(float)
        rolling_mean = values.rolling(window=3, min_periods=3).mean()
        return pd.DataFrame({self.factor_id: rolling_mean.values}, index=df.index)


class MainNetPct5dFactor(FactorPlugin):
    """5日主力净流入占比均值因子 — 主流多周期统计，反映主力持续态度。

    经济含义：5日（约1周）是业界主流的资金流观察周期；
              能有效平滑单日噪音，同时保持合理的响应速度。
    对标：东方财富/同花顺均提供 5日主力资金净流入统计。
    """

    factor_id: str = "main_net_pct_5d"
    display_name: str = "5日主力净流入占比均值"
    category: str = "fund_flow"
    group_id: str = "main_net_pct_5d"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["main_net_pct"]
    min_periods: int = 5
    requires_full_history: bool = True
    data_origin: str = "fund_flow"
    data_start_date: date = _FUND_FLOW_DATA_START

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        values = df["main_net_pct"].astype(float)
        rolling_mean = values.rolling(window=5, min_periods=5).mean()
        return pd.DataFrame({self.factor_id: rolling_mean.values}, index=df.index)


# ── 时序变化因子 ──


class MainNetPctChgFactor(FactorPlugin):
    """主力净流入占比变化因子 — diff(1)，捕捉资金流加速度。

    经济含义：资金流加速流入（正值）= 主力进场意愿增强；
              减速或流出加速（负值）= 接近完成建仓或开始撤离。
              是单日值的自然补充，反映主力行为的"二阶导数"。
    """

    factor_id: str = "main_net_pct_chg"
    display_name: str = "主力净流入占比变化"
    category: str = "fund_flow"
    group_id: str = "main_net_pct_chg"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["main_net_pct"]
    min_periods: int = 2
    requires_full_history: bool = True
    data_origin: str = "fund_flow"
    data_start_date: date = _FUND_FLOW_DATA_START

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        values = df["main_net_pct"].astype(float)
        diff = values.diff(periods=1)
        return pd.DataFrame({self.factor_id: diff.values}, index=df.index)
