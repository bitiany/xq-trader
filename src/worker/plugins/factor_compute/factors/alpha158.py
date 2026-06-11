"""Alpha158 量价因子 — Qlib Alpha158 代表性因子。

参照 factor-catalog v5.0 "变化优先"原则：
  - kmid_5: 5日K线实体均值，量价形态
  - klen_5: 5日K线振幅均值，波动率代理
  - kup2_5: 5日上影线占比均值，压力信号
  - klow2_5: 5日下影线占比均值，支撑信号
  - rsv_9: 9日随机值，超买超卖
  - cntp_20: 20日上涨天数占比，趋势强度
  - imax_20: 20日最高价位置，动量衰减
  - roc5_close: 5日收盘变化率，短期动量
  - std20_close: 20日收盘波动率，变异系数
  - corr_pv_10: 10日价量相关，流动性信号

因子ID：
  - kmid_5 / klen_5 / kup2_5 / klow2_5: K线形态因子组
  - rsv_9: 随机值
  - cntp_20: 上涨天数占比
  - imax_20: 最高价位置
  - roc5_close: 收盘变化率
  - std20_close: 收盘波动率
  - corr_pv_10: 价量相关
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from xqtrader.domain.factor.base import FactorPlugin


class Kmid5Factor(FactorPlugin):
    """5日K线实体均值因子 — ((C-O)/O).rolling(5).mean()，量价形态。"""

    factor_id: str = "kmid_5"
    display_name: str = "5日K线实体均值"
    category: str = "alpha158"
    group_id: str = "kmid"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close", "open"]
    min_periods: int = 5
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        open_ = df["open"].astype(float)
        result = ((close - open_) / open_).rolling(5).mean()
        return pd.DataFrame({self.factor_id: result.values}, index=df.index)


class Klen5Factor(FactorPlugin):
    """5日K线振幅均值因子 — ((H-L)/O).rolling(5).mean()，波动率代理。"""

    factor_id: str = "klen_5"
    display_name: str = "5日K线振幅均值"
    category: str = "alpha158"
    group_id: str = "klen"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["high", "low", "open"]
    min_periods: int = 5
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        open_ = df["open"].astype(float)
        result = ((high - low) / open_).rolling(5).mean()
        return pd.DataFrame({self.factor_id: result.values}, index=df.index)


class Kup25Factor(FactorPlugin):
    """5日上影线占比均值因子 — (H-max(O,C))/(H-L+ε).rolling(5).mean()，压力信号。"""

    factor_id: str = "kup2_5"
    display_name: str = "5日上影线占比均值"
    category: str = "alpha158"
    group_id: str = "kup2"
    direction: str = "ASC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["high", "open", "close", "low"]
    min_periods: int = 5
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        high = df["high"].astype(float)
        open_ = df["open"].astype(float)
        close = df["close"].astype(float)
        low = df["low"].astype(float)
        upper_shadow = (high - np.maximum(open_, close)) / (high - low + 1e-12)
        result = upper_shadow.rolling(5).mean()
        return pd.DataFrame({self.factor_id: result.values}, index=df.index)


class Klow25Factor(FactorPlugin):
    """5日下影线占比均值因子 — (min(O,C)-L)/(H-L+ε).rolling(5).mean()，支撑信号。"""

    factor_id: str = "klow2_5"
    display_name: str = "5日下影线占比均值"
    category: str = "alpha158"
    group_id: str = "klow2"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["low", "open", "close", "high"]
    min_periods: int = 5
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        low = df["low"].astype(float)
        open_ = df["open"].astype(float)
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        lower_shadow = (np.minimum(open_, close) - low) / (high - low + 1e-12)
        result = lower_shadow.rolling(5).mean()
        return pd.DataFrame({self.factor_id: result.values}, index=df.index)


class Rsv9Factor(FactorPlugin):
    """9日随机值因子 — (C-L9)/(H9-L9+ε)，超买超卖。"""

    factor_id: str = "rsv_9"
    display_name: str = "9日随机值"
    category: str = "alpha158"
    group_id: str = "rsv"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close", "high", "low"]
    min_periods: int = 9
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        lowest_9 = low.rolling(9).min()
        highest_9 = high.rolling(9).max()
        result = (close - lowest_9) / (highest_9 - lowest_9 + 1e-12)
        return pd.DataFrame({self.factor_id: result.values}, index=df.index)


class Cntp20Factor(FactorPlugin):
    """20日上涨天数占比因子 — (ΔC>0).rolling(20).mean()，趋势强度。"""

    factor_id: str = "cntp_20"
    display_name: str = "20日上涨天数占比"
    category: str = "alpha158"
    group_id: str = "cntp"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 20
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        result = (close.diff() > 0).rolling(20).mean()
        return pd.DataFrame({self.factor_id: result.values}, index=df.index)


class Imax20Factor(FactorPlugin):
    """20日最高价位置因子 — argmax(C,20)/20，动量衰减。"""

    factor_id: str = "imax_20"
    display_name: str = "20日最高价位置"
    category: str = "alpha158"
    group_id: str = "imax"
    direction: str = "ASC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 20
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        result = close.rolling(20).apply(lambda x: np.argmax(x), raw=True) / 20
        return pd.DataFrame({self.factor_id: result.values}, index=df.index)


class Roc5CloseFactor(FactorPlugin):
    """5日收盘变化率因子 — C.pct_change(5)，短期动量。"""

    factor_id: str = "roc5_close"
    display_name: str = "5日收盘变化率"
    category: str = "alpha158"
    group_id: str = "roc5_close"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 6
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        result = close.pct_change(5)
        return pd.DataFrame({self.factor_id: result.values}, index=df.index)


class Std20CloseFactor(FactorPlugin):
    """20日收盘波动率因子 — std(C,20)/mean(C,20)，变异系数。"""

    factor_id: str = "std20_close"
    display_name: str = "20日收盘波动率"
    category: str = "alpha158"
    group_id: str = "std20_close"
    direction: str = "ASC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 20
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        rolling_std = close.rolling(20).std()
        rolling_mean = close.rolling(20).mean()
        result = rolling_std / rolling_mean.replace(0, np.nan)
        return pd.DataFrame({self.factor_id: result.values}, index=df.index)


class CorrPv10Factor(FactorPlugin):
    """10日价量相关因子 — corr(C, log1p(V), 10)，流动性信号。"""

    factor_id: str = "corr_pv_10"
    display_name: str = "10日价量相关"
    category: str = "alpha158"
    group_id: str = "corr_pv_10"
    direction: str = "ASC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close", "volume"]
    min_periods: int = 10
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        volume = df["volume"].astype(float)
        result = close.rolling(10).corr(np.log1p(volume))
        return pd.DataFrame({self.factor_id: result.values}, index=df.index)
