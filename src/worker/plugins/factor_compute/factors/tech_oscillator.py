"""技术振荡器因子 — RSI / KDJ / CCI / WR / BIAS。

组合因子 KDJ 输出 kdj_k / kdj_d / kdj_j 三个因子。
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import talib  # type: ignore[import-not-found]

from xqtrader.domain.factor.base import FactorPlugin


class RSIFactor(FactorPlugin):
    """相对强弱指标因子。"""

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


class KDJFactor(FactorPlugin):
    """KDJ 组合因子 — 输出 kdj_k / kdj_d / kdj_j。"""

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
            slowk_matype=0,
            slowd_period=self.slowd,
            slowd_matype=0,
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
    """威廉指标因子。"""

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
        _id_map = {14: "wr_14"}
        self.factor_id = _id_map.get(period, f"wr_{period}")
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
    """乖离率因子。"""

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
        bias = (close - ma) / ma * 100
        return pd.DataFrame({self.factor_id: bias.values}, index=df.index)
