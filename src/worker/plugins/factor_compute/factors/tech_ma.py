"""均线偏离因子 — MA偏离度 / MA偏离度变化。

参照 factor-catalog v5.0 "变化优先"原则：
  - 原始均线值(MA/EMA)无截面可比性，不同价格股票间不可比较
  - 均线偏离度 = MA(close, N) / close - 1，标准化为比率，截面可比
  - 均线偏离度变化 = Δ(偏离度)，反映偏离度加速回归，预测力更强

因子ID：
  - ma_bias_5 / ma_bias_10 / ma_bias_20 / ma_bias_60: 均线偏离度
  - ma_bias_delta_20: 20日均线偏离度变化率
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import talib  # type: ignore[import-not-found]

from xqtrader.domain.factor.base import FactorPlugin


class MABiasFactor(FactorPlugin):
    """均线偏离度因子 — MA(N)/close - 1。

    偏离度为正表示均线在价格上方（超卖区间），为负表示均线在价格下方（超买区间）。
    截面可比：不同价格股票的偏离度可直接比较。
    """

    factor_id: str = ""
    display_name: str = ""
    category: str = "tech_ma"
    group_id: str = "ma_bias"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 5
    requires_full_history: bool = False

    def __init__(self, period: int = 20, **kwargs: Any) -> None:
        self.period = period
        self.factor_id = f"ma_bias_{period}"
        self.display_name = f"MA{period}偏离度"
        self.min_periods = period
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].to_numpy(dtype=np.float64)
        ma = talib.MA(close, timeperiod=self.period)
        with np.errstate(divide="ignore", invalid="ignore"):
            bias = np.where(close != 0, ma / close - 1, np.nan)
        return pd.DataFrame({self.factor_id: bias}, index=df.index)


class MABiasDeltaFactor(FactorPlugin):
    """均线偏离度变化率因子 — Δ(MA(N)/close - 1)。

    偏离度变化反映价格向均线回归的加速度：
    - 正值：偏离度在扩大（价格远离均线）
    - 负值：偏离度在缩小（价格回归均线）
    核心均线因子——"均值回归加速"信号。
    """

    factor_id: str = ""
    display_name: str = ""
    category: str = "tech_ma"
    group_id: str = "ma_bias_delta"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 21
    requires_full_history: bool = False

    def __init__(self, period: int = 20, **kwargs: Any) -> None:
        self.period = period
        self.factor_id = f"ma_bias_delta_{period}"
        self.display_name = f"MA{period}偏离度变化"
        self.min_periods = period + 1
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].to_numpy(dtype=np.float64)
        ma = talib.MA(close, timeperiod=self.period)
        with np.errstate(divide="ignore", invalid="ignore"):
            bias = np.where(close != 0, ma / close - 1, np.nan)
        bias_delta = pd.Series(bias).diff().values
        return pd.DataFrame({self.factor_id: bias_delta}, index=df.index)
