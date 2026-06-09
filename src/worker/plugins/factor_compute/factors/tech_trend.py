"""技术趋势因子 — MACD / ADX / BOLL / SAR。

MACD: 组合因子，输出 macd_dif / macd_dea / macd_hist
ADX: 组合因子，输出 adx_14 / adx_plus_di / adx_minus_di
BOLL: 组合因子，输出 boll_upper / boll_middle / boll_lower / boll_width
SAR: 单因子
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import talib  # type: ignore[import-not-found]

from xqtrader.domain.factor.base import FactorPlugin


class MACDFactor(FactorPlugin):
    """MACD 组合因子 — 输出 macd_dif / macd_dea / macd_hist。"""

    factor_id: str = "macd"
    display_name: str = "MACD组合"
    category: str = "tech_trend"
    group_id: str = "macd"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 35
    requires_full_history: bool = True
    is_composite: bool = True
    composite_factor_ids: list[str] = ["macd_dif", "macd_dea", "macd_hist"]

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9, **kwargs: Any) -> None:
        self.fast = fast
        self.slow = slow
        self.signal_period = signal
        self.min_periods = slow + signal
        self.params = {"fast": fast, "slow": slow, "signal": signal}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].values.astype(float)
        dif, dea, hist = talib.MACD(
            close, fastperiod=self.fast, slowperiod=self.slow, signalperiod=self.signal_period,
        )
        hist = hist * 2
        return pd.DataFrame(
            {"macd_dif": dif, "macd_dea": dea, "macd_hist": hist},
            index=df.index,
        )


class ADXFactor(FactorPlugin):
    """ADX 组合因子 — 输出 adx_14 / adx_plus_di / adx_minus_di。"""

    factor_id: str = "adx"
    display_name: str = "ADX组合"
    category: str = "tech_trend"
    group_id: str = "adx"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["high", "low", "close"]
    min_periods: int = 28
    requires_full_history: bool = True
    is_composite: bool = True
    composite_factor_ids: list[str] = ["adx_14", "adx_plus_di", "adx_minus_di"]

    def __init__(self, period: int = 14, **kwargs: Any) -> None:
        self.period = period
        self.min_periods = period * 2
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        high = df["high"].values.astype(float)
        low = df["low"].values.astype(float)
        close = df["close"].values.astype(float)
        adx = talib.ADX(high, low, close, timeperiod=self.period)
        plus_di = talib.PLUS_DI(high, low, close, timeperiod=self.period)
        minus_di = talib.MINUS_DI(high, low, close, timeperiod=self.period)
        return pd.DataFrame(
            {"adx_14": adx, "adx_plus_di": plus_di, "adx_minus_di": minus_di},
            index=df.index,
        )


class BOLLFactor(FactorPlugin):
    """布林带组合因子 — 输出 boll_upper / boll_middle / boll_lower / boll_width。"""

    factor_id: str = "boll"
    display_name: str = "BOLL组合"
    category: str = "tech_trend"
    group_id: str = "boll"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 20
    requires_full_history: bool = False
    is_composite: bool = True
    composite_factor_ids: list[str] = ["boll_upper", "boll_middle", "boll_lower", "boll_width"]

    def __init__(self, period: int = 20, nbdev: int = 2, **kwargs: Any) -> None:
        self.period = period
        self.nbdev = nbdev
        self.min_periods = period
        self.params = {"period": period, "nbdev": nbdev}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].values.astype(float)
        upper, mid, lower = talib.BBANDS(
            close, timeperiod=self.period, nbdevup=self.nbdev, nbdevdn=self.nbdev,
        )
        width = (upper - lower) / mid * 100
        return pd.DataFrame(
            {"boll_upper": upper, "boll_middle": mid, "boll_lower": lower, "boll_width": width},
            index=df.index,
        )


class SARFactor(FactorPlugin):
    """抛物线指标因子。"""

    factor_id: str = "sar"
    display_name: str = "抛物线指标"
    category: str = "tech_trend"
    group_id: str = "sar"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["high", "low", "close"]
    min_periods: int = 5
    requires_full_history: bool = True

    def __init__(self, acceleration: float = 0.02, maximum: float = 0.2, **kwargs: Any) -> None:
        self.acceleration = acceleration
        self.maximum = maximum
        self.params = {"acceleration": acceleration, "maximum": maximum}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        high = df["high"].values.astype(float)
        low = df["low"].values.astype(float)
        sar = talib.SAR(high, low, acceleration=self.acceleration, maximum=self.maximum)
        return pd.DataFrame({self.factor_id: sar}, index=df.index)
