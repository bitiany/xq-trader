"""技术波动率因子 — ATR比率 / ATR比率变化 / 历史波动率 / NATR / 下行波动率 / Amihud / 量振荡 / ADV。

参照 factor-catalog v5.0 "变化优先"原则：
  - ATR原始值无截面可比性，改为 ATR/close 和 Δ(ATR/close)
  - 历史波动率基于收益率标准差，已是截面可比
  - NATR = ATR/close*100，已标准化
  - Amihud = |ret|/amount，已是比率

因子ID：
  - atr_ratio: ATR(14)/close（标准化波动率）
  - atr_ratio_delta: Δ(ATR(14)/close)（波动率加速）
  - hist_vol_10 / hist_vol_20 / hist_vol_60: 历史波动率
  - natr_14: 归一化ATR
  - downside_vol: 下行波动率
  - amihud: Amihud非流动性
  - vol_osc: 成交量振荡
  - adv_20: 20日均量偏离
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import talib  # type: ignore[import-not-found]

from xqtrader.domain.factor.base import FactorPlugin


class ATRRatioFactor(FactorPlugin):
    """ATR/价格因子 — ATR(14)/close，标准化波动率，截面可比。

    ATR原始值依赖价格水平（高价股ATR大），除以close后截面可比。
    """

    factor_id: str = "atr_ratio"
    display_name: str = "ATR/价格"
    category: str = "tech_volatility"
    group_id: str = "atr"
    direction: str = "ASC"
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
        ratio = np.where(close != 0, atr / close, np.nan)
        return pd.DataFrame({self.factor_id: ratio}, index=df.index)


class ATRRatioDeltaFactor(FactorPlugin):
    """ATR/价格变化率因子 — Δ(ATR(14)/close)，波动率加速。

    波动率变化比波动率水平更预测收益——波动率从低位突然放大是重要信号。
    """

    factor_id: str = "atr_ratio_delta"
    display_name: str = "ATR/价格变化"
    category: str = "tech_volatility"
    group_id: str = "atr"
    direction: str = "ASC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["high", "low", "close"]
    min_periods: int = 16
    requires_full_history: bool = True

    def __init__(self, period: int = 14, **kwargs: Any) -> None:
        self.period = period
        self.min_periods = period + 2
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        high = df["high"].values.astype(float)
        low = df["low"].values.astype(float)
        close = df["close"].values.astype(float)
        atr = talib.ATR(high, low, close, timeperiod=self.period)
        ratio = np.where(close != 0, atr / close, np.nan)
        delta = pd.Series(ratio).diff().values
        return pd.DataFrame({self.factor_id: delta}, index=df.index)


class VolatilityFactor(FactorPlugin):
    """历史波动率因子（收益率标准差×√252），截面可比。"""

    factor_id: str = ""
    display_name: str = ""
    category: str = "tech_volatility"
    group_id: str = "hist_vol"
    direction: str = "ASC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 10
    requires_full_history: bool = False

    def __init__(self, period: int = 20, **kwargs: Any) -> None:
        self.period = period
        self.factor_id = f"hist_vol_{period}"
        self.display_name = f"{period}日历史波动率"
        self.min_periods = period
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        ret = close.pct_change()
        vol = ret.rolling(window=self.period).std() * np.sqrt(252)
        return pd.DataFrame({self.factor_id: vol.values}, index=df.index)


class NatrFactor(FactorPlugin):
    """归一化平均真实波幅因子 — NATR = ATR/close*100，已标准化。"""

    factor_id: str = "natr_14"
    display_name: str = "NATR(14)"
    category: str = "tech_volatility"
    group_id: str = "natr"
    direction: str = "ASC"
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
    """下行波动率因子 — 负收益日标准差×√252，截面可比。"""

    factor_id: str = ""
    display_name: str = ""
    category: str = "tech_volatility"
    group_id: str = "downside_vol"
    direction: str = "ASC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 20
    requires_full_history: bool = False

    def __init__(self, period: int = 20, **kwargs: Any) -> None:
        self.period = period
        self.factor_id = f"downside_vol_{period}" if period != 20 else "downside_vol"
        self.display_name = f"下行波动率({period})"
        self.min_periods = period
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        ret = close.pct_change()
        down_ret = ret.clip(upper=0)
        down_vol = (down_ret**2).rolling(window=self.period).mean().pipe(np.sqrt) * np.sqrt(252)
        return pd.DataFrame({self.factor_id: down_vol.values}, index=df.index)


class AmihudFactor(FactorPlugin):
    """Amihud 非流动性因子 — |ret|/amount，已是比率形式。"""

    factor_id: str = ""
    display_name: str = ""
    category: str = "tech_volatility"
    group_id: str = "amihud"
    direction: str = "ASC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close", "amount"]
    min_periods: int = 20
    requires_full_history: bool = False

    def __init__(self, period: int = 20, **kwargs: Any) -> None:
        self.period = period
        self.factor_id = f"amihud_{period}" if period != 20 else "amihud"
        self.display_name = f"Amihud({period})"
        self.min_periods = period
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        amount = df["amount"].astype(float)
        ret = close.pct_change().abs()
        amihud = (ret / amount.abs().replace(0, np.nan)).rolling(window=self.period).mean()
        return pd.DataFrame({self.factor_id: amihud.values}, index=df.index)


class VolOscFactor(FactorPlugin):
    """成交量振荡因子 — MA(V,5)/MA(V,20)，已是比率形式。"""

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

    def __init__(self, short_period: int = 5, long_period: int = 20, **kwargs: Any) -> None:
        self.short_period = short_period
        self.long_period = long_period
        self.min_periods = long_period
        self.params = {"short_period": short_period, "long_period": long_period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        volume = df["volume"].astype(float)
        short_ma = volume.rolling(window=self.short_period).mean()
        long_ma = volume.rolling(window=self.long_period).mean()
        vol_osc = short_ma / long_ma.replace(0, np.nan)
        return pd.DataFrame({self.factor_id: vol_osc.values}, index=df.index)


class ADVFactor(FactorPlugin):
    """成交量偏离度因子 — MA(volume,N)/volume，偏离度形式。"""

    factor_id: str = ""
    display_name: str = ""
    category: str = "tech_volatility"
    group_id: str = "adv"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["volume"]
    min_periods: int = 20
    requires_full_history: bool = False

    def __init__(self, period: int = 20, **kwargs: Any) -> None:
        self.period = period
        self.factor_id = f"adv_{period}"
        self.display_name = f"ADV({period})"
        self.min_periods = period
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        volume = df["volume"].astype(float)
        adv = volume.rolling(window=self.period).mean()
        ratio = adv / volume.replace(0, np.nan)
        return pd.DataFrame({self.factor_id: ratio.values}, index=df.index)
