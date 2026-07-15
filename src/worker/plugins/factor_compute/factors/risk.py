"""A 类风险因子 — 对数总市值 / 换手率 / 流通换手率 / 对数成交额 / 量比 / DASTD / CMRA。

参照 factor-catalog v6.0：
  - cs_log_mv: 对数总市值，log(1+total_mv)，截面可比
  - cs_turnover: 换手率，直接取 turnover_rate，截面可比
  - turnover_f: 流通换手率，直接取 turnover_rate_f，截面可比
  - cs_log_amount: 对数成交额，log(1+amount)，截面可比
  - cs_volume_ratio: 量比，当日成交量 / 5日均量
  - dastd: Barra 日收益加权标准差，ewm(halflife=42).std() × √252
  - cmra: Barra 累计收益范围，12个月累计对数收益极差

因子ID：
  - cs_log_mv: 对数总市值
  - cs_turnover: 换手率
  - turnover_f: 流通换手率
  - cs_log_amount: 对数成交额
  - cs_volume_ratio: 量比
  - dastd: 日收益加权标准差
  - cmra: 累计收益范围
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from xqtrader.domain.factor.base import FactorPlugin


class CsLogMvFactor(FactorPlugin):
    """对数总市值因子 — log(1 + total_mv)，截面可比。

    总市值绝对值跨量级差异大，取对数后近似正态分布，截面可比。
    """

    factor_id: str = "cs_log_mv"
    display_name: str = "对数总市值"
    category: str = "risk"
    group_id: str = "cs_log_mv"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["total_mv"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "market"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        total_mv = df["total_mv"].astype(float)
        result = np.log1p(total_mv.abs().replace(0, np.nan))
        return pd.DataFrame({self.factor_id: np.asarray(result)}, index=df.index)


class CsTurnoverFactor(FactorPlugin):
    """换手率因子 — 直接取 turnover_rate，截面可比。"""

    factor_id: str = "cs_turnover"
    display_name: str = "换手率"
    category: str = "risk"
    group_id: str = "cs_turnover"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["turnover_rate"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "market"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        values = df["turnover_rate"].astype(float)
        return pd.DataFrame({self.factor_id: values.values}, index=df.index)


class TurnoverFFactor(FactorPlugin):
    """流通换手率因子 — 直接取 turnover_rate_f，截面可比。"""

    factor_id: str = "turnover_f"
    display_name: str = "流通换手率"
    category: str = "risk"
    group_id: str = "turnover_f"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["turnover_rate_f"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "market"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        values = df["turnover_rate_f"].astype(float)
        return pd.DataFrame({self.factor_id: values.values}, index=df.index)


class CsLogAmountFactor(FactorPlugin):
    """对数成交额因子 — log(1 + amount)，截面可比。

    成交额绝对值跨量级差异大，取对数后近似正态分布，截面可比。
    """

    factor_id: str = "cs_log_amount"
    display_name: str = "对数成交额"
    category: str = "risk"
    group_id: str = "cs_log_amount"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["amount"]
    min_periods: int = 1
    requires_full_history: bool = False
    data_origin: str = "computed"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        amount = df["amount"].astype(float)
        result = np.log1p(amount.abs().replace(0, np.nan))
        return pd.DataFrame({self.factor_id: np.asarray(result)}, index=df.index)


class CsVolumeRatioFactor(FactorPlugin):
    """量比因子 — 当日成交量 / 5日均量，截面可比。

    量比 > 1 表示放量，< 1 表示缩量。
    """

    factor_id: str = "cs_volume_ratio"
    display_name: str = "量比"
    category: str = "risk"
    group_id: str = "cs_volume_ratio"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["volume"]
    min_periods: int = 5
    requires_full_history: bool = False
    data_origin: str = "computed"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        volume = df["volume"].astype(float)
        vol_ma5 = volume.rolling(window=5, min_periods=5).mean()
        ratio = volume / vol_ma5.replace(0, np.nan)
        return pd.DataFrame({self.factor_id: ratio.values}, index=df.index)


class DastdFactor(FactorPlugin):
    """Barra 日收益加权标准差因子 — ewm(halflife=42).std() × √252。

    DASTD (Daily Return Standard Deviation) 使用指数加权标准差，
    半衰期42天，年化后截面可比。波动率越大风险越高，direction=ASC。
    """

    factor_id: str = "dastd"
    display_name: str = "日收益加权标准差"
    category: str = "risk"
    group_id: str = "dastd"
    direction: str = "ASC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 42
    requires_full_history: bool = False
    data_origin: str = "computed"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        ret = close.pct_change()
        dastd = ret.ewm(halflife=42, min_periods=self.min_periods).std() * np.sqrt(252)
        return pd.DataFrame({self.factor_id: dastd.values}, index=df.index)


class CmraFactor(FactorPlugin):
    """Barra 累计收益范围因子 — 12个月累计对数收益极差。

    CMRA (Cumulative Range) = max(cum_log_ret, 252) - min(cum_log_ret, 252)
    衡量长期收益波动幅度，极差越大风险越高，direction=ASC。
    """

    factor_id: str = "cmra"
    display_name: str = "累计收益范围"
    category: str = "risk"
    group_id: str = "cmra"
    direction: str = "ASC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 252
    requires_full_history: bool = False
    data_origin: str = "computed"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        ret = close.pct_change()
        with np.errstate(divide="ignore", invalid="ignore"):
            cum_log_ret = pd.Series(np.log1p(ret.to_numpy()), index=ret.index).cumsum()
        cmra = (
            cum_log_ret.rolling(window=252, min_periods=self.min_periods).max()
            - cum_log_ret.rolling(window=252, min_periods=self.min_periods).min()
        )
        return pd.DataFrame({self.factor_id: cmra.values}, index=df.index)
