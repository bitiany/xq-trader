"""技术振荡器因子 — RSI / RSI变化 / KDJ / CCI / WR / BIAS。

参照 factor-catalog v5.0 "变化优先"原则：
  - RSI 本身 0-100 范围截面可比，新增 RSI 变化率因子
  - KDJ 值域 0-100 截面可比
  - BIAS 已是比率形式，截面可比
  - CCI / WR 无需标准化

因子ID：
  - rsi_6 / rsi_14 / rsi_24: RSI
  - rsi_delta_14: RSI(14)变化率
  - kdj_k / kdj_d / kdj_j: KDJ组合
  - cci_14: CCI
  - wr_14: WR
  - bias_6 / bias_12 / bias_24: 乖离率
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import talib  # type: ignore[import-not-found]

from xqtrader.domain.factor.base import FactorPlugin


class RSIFactor(FactorPlugin):
    """相对强弱指标因子 — 0-100范围，截面可比。"""

    factor_id: str = ""
    display_name: str = ""
    category: str = "tech_oscillator"
    group_id: str = "rsi"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 15
    requires_full_history: bool = True

    def __init__(self, period: int = 14, **kwargs: Any) -> None:
        self.period = period
        self.factor_id = f"rsi_{period}"
        self.display_name = f"RSI({period})"
        self.min_periods = period + 1
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].values.astype(float)
        rsi = talib.RSI(close, timeperiod=self.period)
        return pd.DataFrame({self.factor_id: rsi}, index=df.index)


class RSIDeltaFactor(FactorPlugin):
    """RSI变化率因子 — Δ(RSI(N))，超买超卖加速。

    RSI从60→70比RSI=70更有信息量，变化率捕捉超买超卖的加速/减速。
    """

    factor_id: str = ""
    display_name: str = ""
    category: str = "tech_oscillator"
    group_id: str = "rsi_delta"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 16
    requires_full_history: bool = True

    def __init__(self, period: int = 14, **kwargs: Any) -> None:
        self.period = period
        self.factor_id = f"rsi_delta_{period}"
        self.display_name = f"RSI({period})变化"
        self.min_periods = period + 2
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].values.astype(float)
        rsi = talib.RSI(close, timeperiod=self.period)
        delta = pd.Series(rsi).diff().values
        return pd.DataFrame({self.factor_id: delta}, index=df.index)


class KDJFactor(FactorPlugin):
    """KDJ 组合因子 — 输出 kdj_k / kdj_d / kdj_j，值域 0-100 截面可比。"""

    factor_id: str = "kdj"
    display_name: str = "KDJ组合"
    category: str = "tech_oscillator"
    group_id: str = "kdj"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["high", "low", "close"]
    min_periods: int = 12
    requires_full_history: bool = True
    is_composite: bool = True
    composite_factor_ids: list[str] = ["kdj_k", "kdj_d", "kdj_j"]

    def __init__(self, fastk: int = 9, slowk: int = 3, slowd: int = 3, **kwargs: Any) -> None:
        self.fastk = fastk
        self.slowk = slowk
        self.slowd = slowd
        self.min_periods = fastk + slowk
        self.params = {"fastk": fastk, "slowk": slowk, "slowd": slowd}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        high = df["high"].values.astype(float)
        low = df["low"].values.astype(float)
        close = df["close"].values.astype(float)
        k, d = talib.STOCH(
            high, low, close,
            fastk_period=self.fastk,
            slowk_period=self.slowk,
            slowk_matype=0,  # type: ignore[arg-type]
            slowd_period=self.slowd,
            slowd_matype=0,  # type: ignore[arg-type]
        )
        j = 3 * k - 2 * d
        return pd.DataFrame({"kdj_k": k, "kdj_d": d, "kdj_j": j}, index=df.index)


class CCIFactor(FactorPlugin):
    """商品通道指标因子。"""

    factor_id: str = ""
    display_name: str = ""
    category: str = "tech_oscillator"
    group_id: str = "cci"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["high", "low", "close"]
    min_periods: int = 15
    requires_full_history: bool = True

    def __init__(self, period: int = 14, **kwargs: Any) -> None:
        self.period = period
        self.factor_id = f"cci_{period}"
        self.display_name = f"CCI({period})"
        self.min_periods = period + 1
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        high = df["high"].values.astype(float)
        low = df["low"].values.astype(float)
        close = df["close"].values.astype(float)
        cci = talib.CCI(high, low, close, timeperiod=self.period)
        return pd.DataFrame({self.factor_id: cci}, index=df.index)


class WILLRFactor(FactorPlugin):
    """威廉指标因子 — 0-100范围，截面可比。"""

    factor_id: str = ""
    display_name: str = ""
    category: str = "tech_oscillator"
    group_id: str = "willr"
    direction: str = "ASC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["high", "low", "close"]
    min_periods: int = 15
    requires_full_history: bool = True

    def __init__(self, period: int = 14, **kwargs: Any) -> None:
        self.period = period
        self.factor_id = f"wr_{period}"
        self.display_name = f"WR({period})"
        self.min_periods = period + 1
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        high = df["high"].values.astype(float)
        low = df["low"].values.astype(float)
        close = df["close"].values.astype(float)
        willr = talib.WILLR(high, low, close, timeperiod=self.period)
        return pd.DataFrame({self.factor_id: willr}, index=df.index)


class BIASFactor(FactorPlugin):
    """乖离率因子 — (close - MA) / MA * 100，已是比率形式，截面可比。"""

    factor_id: str = ""
    display_name: str = ""
    category: str = "tech_oscillator"
    group_id: str = "bias"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 6

    def __init__(self, period: int = 6, **kwargs: Any) -> None:
        self.period = period
        self.factor_id = f"bias_{period}"
        self.display_name = f"BIAS({period})"
        self.min_periods = period + 1
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        ma = close.rolling(window=self.period).mean()
        bias = np.where(ma != 0, (close - ma) / ma * 100, np.nan)
        return pd.DataFrame({self.factor_id: bias}, index=df.index)
