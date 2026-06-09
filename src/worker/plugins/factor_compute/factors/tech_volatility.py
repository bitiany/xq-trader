"""技术波动率因子 — ATR / Volatility / NATR / DownsideVol / Amihud / VolOsc / ADV。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import talib  # type: ignore[import-not-found]

from xqtrader.domain.factor.base import FactorPlugin


class ATRFactor(FactorPlugin):
    """平均真实波幅因子。"""

    factor_id: str = "atr_14"
    display_name: str = "ATR(14)"
    category: str = "tech_volatility"
    group_id: str = "atr"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["high", "low", "close"]
    min_periods: int = 15
    requires_full_history: bool = True

    def __init__(self, period: int = 14, **kwargs: Any) -> None:
        self.period = period
        self.min_periods = period + 1
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        high = df["high"].values.astype(float)
        low = df["low"].values.astype(float)
        close = df["close"].values.astype(float)
        atr = talib.ATR(high, low, close, timeperiod=self.period)
        return pd.DataFrame({self.factor_id: atr}, index=df.index)


class VolatilityFactor(FactorPlugin):
    """历史波动率因子（收益率标准差）。"""

    factor_id: str = ""
    display_name: str = ""
    category: str = "tech_volatility"
    group_id: str = "volatility"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 10
    requires_full_history: bool = False

    def __init__(self, period: int = 20, **kwargs: Any) -> None:
        self.period = period
        self.factor_id = f"volatility_{period}"
        self.display_name = f"Volatility({period})"
        self.min_periods = period
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        ret = close.pct_change()
        vol = ret.rolling(window=self.period).std() * np.sqrt(252)
        return pd.DataFrame({self.factor_id: vol.values}, index=df.index)


class NatrFactor(FactorPlugin):
    """归一化平均真实波幅因子。"""

    factor_id: str = "natr_14"
    display_name: str = "NATR(14)"
    category: str = "tech_volatility"
    group_id: str = "natr"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["high", "low", "close"]
    min_periods: int = 15
    requires_full_history: bool = True

    def __init__(self, period: int = 14, **kwargs: Any) -> None:
        self.period = period
        self.min_periods = period + 1
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        high = df["high"].values.astype(float)
        low = df["low"].values.astype(float)
        close = df["close"].values.astype(float)
        natr = talib.NATR(high, low, close, timeperiod=self.period)
        return pd.DataFrame({self.factor_id: natr}, index=df.index)


class DownsideVolFactor(FactorPlugin):
    """下行波动率因子。"""

    factor_id: str = "downside_vol"
    display_name: str = "下行波动率"
    category: str = "tech_volatility"
    group_id: str = "downside_vol"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 20
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        ret = close.pct_change()
        down_ret = ret.where(ret < 0, 0)
        down_vol = down_ret.rolling(window=20).std() * np.sqrt(252)
        return pd.DataFrame({self.factor_id: down_vol.values}, index=df.index)


class AmihudFactor(FactorPlugin):
    """Amihud 非流动性因子。"""

    factor_id: str = "amihud_20"
    display_name: str = "Amihud(20)"
    category: str = "tech_volatility"
    group_id: str = "amihud"
    direction: str = "ASC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close", "amount"]
    min_periods: int = 20
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        amount = df["amount"].astype(float)
        ret = close.pct_change().abs()
        amihud = (ret / amount.abs().replace(0, np.nan)).rolling(window=20).mean()
        return pd.DataFrame({self.factor_id: amihud.values}, index=df.index)


class VolOscFactor(FactorPlugin):
    """成交量振荡因子。"""

    factor_id: str = "vol_osc"
    display_name: str = "成交量振荡"
    category: str = "tech_volatility"
    group_id: str = "vol_osc"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["volume"]
    min_periods: int = 20
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        volume = df["volume"].astype(float)
        short_ma = volume.rolling(window=5).mean()
        long_ma = volume.rolling(window=20).mean()
        vol_osc = (short_ma - long_ma) / long_ma.replace(0, np.nan) * 100
        return pd.DataFrame({self.factor_id: vol_osc.values}, index=df.index)


class ADVFactor(FactorPlugin):
    """平均成交额因子。"""

    factor_id: str = "adv_20"
    display_name: str = "ADV(20)"
    category: str = "tech_volatility"
    group_id: str = "adv"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["amount"]
    min_periods: int = 20
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        amount = df["amount"].astype(float)
        adv = amount.rolling(window=20).mean()
        return pd.DataFrame({self.factor_id: adv.values}, index=df.index)
