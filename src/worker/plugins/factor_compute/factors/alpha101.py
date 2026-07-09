"""Alpha101 量价因子 — WorldQuant Alpha101 代表性因子。

参照 factor-catalog v5.0 "变化优先"原则：
  - alpha_12: 量增价跌反转，量价背离信号
  - alpha_101: 日内K线形态，实体占振幅比例
  - alpha_55: 日内涨跌量相关，价量相关性反转
  - alpha_1: 量价偏离极值日，极值位置信号
  - alpha_33: 收开盘比衰减，均值回归信号
  - alpha_41: 几何均价VWAP偏离，价格结构异常

因子ID：
  - alpha_12: 量增价跌反转
  - alpha_101: 日内K线形态
  - alpha_55: 日内涨跌量相关
  - alpha_1: 量价偏离极值日
  - alpha_33: 收开盘比衰减
  - alpha_41: 几何均价VWAP偏离
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from xqtrader.domain.factor.base import FactorPlugin


class Alpha12Factor(FactorPlugin):
    """量增价跌反转因子 — sign(ΔV) * -Δ(C-O)，量增时价跌加速为负信号。"""

    factor_id: str = "alpha_12"
    display_name: str = "量增价跌反转"
    category: str = "alpha101"
    group_id: str = "alpha_12"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close", "open", "volume"]
    min_periods: int = 2
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        open_ = df["open"].astype(float)
        volume = df["volume"].astype(float)
        result = np.sign(volume.diff()) * -(close - open_).diff()
        return pd.DataFrame({self.factor_id: result.values}, index=df.index)


class Alpha101Factor(FactorPlugin):
    """日内K线形态因子 — (C-O)/(H-L+ε)，实体占振幅比例。"""

    factor_id: str = "alpha_101"
    display_name: str = "日内K线形态"
    category: str = "alpha101"
    group_id: str = "alpha_101"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close", "open", "high", "low"]
    min_periods: int = 1
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        open_ = df["open"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        result = (close - open_) / (high - low + 1e-12)
        return pd.DataFrame({self.factor_id: result.values}, index=df.index)


class Alpha55Factor(FactorPlugin):
    """日内涨跌量相关因子 — -(C-O).rolling(5).corr(V.rank(5))，价量相关性反转。"""

    factor_id: str = "alpha_55"
    display_name: str = "日内涨跌量相关"
    category: str = "alpha101"
    group_id: str = "alpha_55"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close", "open", "volume"]
    min_periods: int = 5
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        open_ = df["open"].astype(float)
        volume = df["volume"].astype(float)
        close_open = close - open_
        volume_rank = volume.rolling(5).rank()
        result = -close_open.rolling(5).corr(volume_rank)
        return pd.DataFrame({self.factor_id: result.values}, index=df.index)


class Alpha1Factor(FactorPlugin):
    """量价偏离极值日因子 — |vwap-0.5*O|.rolling(5).argmax/5，极值位置信号。

    简化实现：无vwap时用 (C+O)/2 替代。
    """

    factor_id: str = "alpha_1"
    display_name: str = "量价偏离极值日"
    category: str = "alpha101"
    group_id: str = "alpha_1"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close", "open", "volume"]
    min_periods: int = 5
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        open_ = df["open"].astype(float)
        vwap_proxy = (close + open_) / 2
        deviation = (vwap_proxy - 0.5 * open_).abs()
        result = deviation.rolling(5).apply(lambda x: np.argmax(x), raw=True) / 5
        return pd.DataFrame({self.factor_id: result.values}, index=df.index)


class Alpha33Factor(FactorPlugin):
    """收盘比衰减因子 — -(C/O).rolling(5).mean().rank()，均值回归信号。

    简化版 decay_linear：用 rolling mean + rank 替代线性衰减加权。
    """

    factor_id: str = "alpha_33"
    display_name: str = "收盘比衰减"
    category: str = "alpha101"
    group_id: str = "alpha_33"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close", "open"]
    min_periods: int = 5
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        open_ = df["open"].astype(float)
        ratio = close / open_
        result = -ratio.rolling(5).mean().rank()
        return pd.DataFrame({self.factor_id: result.values}, index=df.index)


class Alpha41Factor(FactorPlugin):
    """几何均价VWAP偏离因子 — √(H*L) - (H+L+C)/3，价格结构异常。

    几何均价与算术均价之差，反映价格分布偏态。
    """

    factor_id: str = "alpha_41"
    display_name: str = "几何均价VWAP偏离"
    category: str = "alpha101"
    group_id: str = "alpha_41"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["high", "low", "close"]
    min_periods: int = 1
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        geo_mean = np.sqrt(np.where((high > 0) & (low > 0), high * low, np.nan))
        arith_mean = (high + low + close) / 3
        result = geo_mean - arith_mean
        return pd.DataFrame({self.factor_id: result.values}, index=df.index)
