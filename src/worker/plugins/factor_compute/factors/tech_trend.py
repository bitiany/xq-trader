"""技术趋势因子 — MACD标准化 / ADX / BOLL位置 / SAR偏离。

参照 factor-catalog v5.0 "变化优先"原则：
  - MACD原始值(DIF/DEA/HIST)无截面可比性，改为 HIST/close 和 Δ(HIST/close)
  - BOLL原始值(upper/middle/lower)无截面可比性，改为 0-1标准化位置和位置变化
  - SAR原始值无截面可比性，改为偏离度变化率
  - ADX本身0-100范围截面可比，新增变化率因子

因子ID：
  - macd_hist_ratio: MACD柱/价格（标准化动量加速度）
  - macd_hist_delta: MACD柱变化率（动量加速度变化——"红柱缩短"信号）
  - adx_14 / adx_plus_di / adx_minus_di: ADX组合
  - adx_delta: ADX变化率（趋势强度加速）
  - boll_position: 布林带位置（0-1标准化）
  - boll_position_delta: 布林带位置变化
  - boll_width: 布林带宽度（波动率代理）
  - sar_deviation: SAR偏离度变化率
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import talib  # type: ignore[import-not-found]

from xqtrader.domain.factor.base import FactorPlugin


class MACDHistRatioFactor(FactorPlugin):
    """MACD柱/价格因子 — HIST/close，标准化动量加速度。

    MACD HIST 本身是 DIF 的导数（动量加速度），但原始值依赖价格水平。
    除以 close 后截面可比：HIST/close 反映单位价格的动量加速度。
    """

    factor_id: str = "macd_hist_ratio"
    display_name: str = "MACD柱/价格"
    category: str = "tech_trend"
    group_id: str = "macd"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 35
    requires_full_history: bool = True

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9, **kwargs: Any) -> None:
        self.fast = fast
        self.slow = slow
        self.signal_period = signal
        self.min_periods = slow + signal
        self.params = {"fast": fast, "slow": slow, "signal": signal}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].to_numpy(dtype=np.float64)
        _, _, hist = talib.MACD(
            close, fastperiod=self.fast, slowperiod=self.slow, signalperiod=self.signal_period,
        )
        hist = hist * 2
        ratio = hist / close
        return pd.DataFrame({self.factor_id: ratio}, index=df.index)


class MACDHistDeltaFactor(FactorPlugin):
    """MACD柱变化率因子 — Δ(HIST/close)，动量加速度变化。

    "红柱缩短"或"绿柱缩短"信号——MACD核心交易信号。
    HIST/close 是加速度，Δ(HIST/close) 是加速度的变化率。
    """

    factor_id: str = "macd_hist_delta"
    display_name: str = "MACD柱变化率"
    category: str = "tech_trend"
    group_id: str = "macd"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 36
    requires_full_history: bool = True

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9, **kwargs: Any) -> None:
        self.fast = fast
        self.slow = slow
        self.signal_period = signal
        self.min_periods = slow + signal + 1
        self.params = {"fast": fast, "slow": slow, "signal": signal}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].to_numpy(dtype=np.float64)
        _, _, hist = talib.MACD(
            close, fastperiod=self.fast, slowperiod=self.slow, signalperiod=self.signal_period,
        )
        hist = hist * 2
        ratio = hist / close
        delta = pd.Series(ratio).diff().values
        return pd.DataFrame({self.factor_id: delta}, index=df.index)


class ADXFactor(FactorPlugin):
    """ADX 组合因子 — 输出 adx_14 / adx_plus_di / adx_minus_di。

    ADX 值域 0-100，截面可比。+DI/-DI 值域 0-100，截面可比。
    """

    factor_id: str = "adx"
    display_name: str = "ADX组合"
    category: str = "tech_trend"
    group_id: str = "adx"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["high", "low", "close"]
    min_periods: int = 28
    requires_full_history: bool = True
    is_composite: bool = True
    composite_factor_ids: list[str] = ["adx_14", "adx_plus_di", "adx_minus_di"]
    child_display_names: dict[str, str] = {
        "adx_14": "14日ADX",
        "adx_plus_di": "上升方向指标",
        "adx_minus_di": "下降方向指标",
    }

    def __init__(self, period: int = 14, **kwargs: Any) -> None:
        self.period = period
        self.min_periods = period * 2
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        high = df["high"].to_numpy(dtype=np.float64)
        low = df["low"].to_numpy(dtype=np.float64)
        close = df["close"].to_numpy(dtype=np.float64)
        adx = talib.ADX(high, low, close, timeperiod=self.period)
        plus_di = talib.PLUS_DI(high, low, close, timeperiod=self.period)
        minus_di = talib.MINUS_DI(high, low, close, timeperiod=self.period)
        return pd.DataFrame(
            {"adx_14": adx, "adx_plus_di": plus_di, "adx_minus_di": minus_di},
            index=df.index,
        )


class ADXDeltaFactor(FactorPlugin):
    """ADX变化率因子 — Δ(ADX(14))，趋势强度加速。

    ADX从20→30比ADX=30更有信息量，变化率捕捉趋势强度的加速/减速。
    """

    factor_id: str = "adx_delta"
    display_name: str = "ADX变化"
    category: str = "tech_trend"
    group_id: str = "adx_delta"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["high", "low", "close"]
    min_periods: int = 29
    requires_full_history: bool = True

    def __init__(self, period: int = 14, **kwargs: Any) -> None:
        self.period = period
        self.min_periods = period * 2 + 1
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        high = df["high"].to_numpy(dtype=np.float64)
        low = df["low"].to_numpy(dtype=np.float64)
        close = df["close"].to_numpy(dtype=np.float64)
        adx = talib.ADX(high, low, close, timeperiod=self.period)
        delta = pd.Series(adx).diff().values
        return pd.DataFrame({self.factor_id: delta}, index=df.index)


class BOLLPositionFactor(FactorPlugin):
    """布林带位置组合因子 — 输出 boll_position / boll_position_delta / boll_width。

    boll_position: (close - lower) / (upper - lower)，0-1标准化位置，截面可比
    boll_position_delta: Δ(boll_position)，位置加速变化——"从下轨回归"信号
    boll_width: (upper - lower) / middle，波动率代理
    """

    factor_id: str = "boll"
    display_name: str = "BOLL组合"
    category: str = "tech_trend"
    group_id: str = "boll"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 20
    requires_full_history: bool = False
    is_composite: bool = True
    composite_factor_ids: list[str] = ["boll_position", "boll_position_delta", "boll_width"]
    child_display_names: dict[str, str] = {
        "boll_position": "布林带位置",
        "boll_position_delta": "布林带位置变化",
        "boll_width": "布林带宽度",
    }

    def __init__(self, period: int = 20, nbdev: int = 2, **kwargs: Any) -> None:
        self.period = period
        self.nbdev = nbdev
        self.min_periods = period
        self.params = {"period": period, "nbdev": nbdev}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].to_numpy(dtype=np.float64)
        upper, mid, lower = talib.BBANDS(
            close, timeperiod=self.period, nbdevup=self.nbdev, nbdevdn=self.nbdev,
        )
        with np.errstate(divide="ignore", invalid="ignore"):
            width = (upper - lower) / np.where(mid != 0, mid, np.nan)
            band_range = upper - lower
            position = np.where(
                band_range != 0,
                (close - lower) / band_range,
                np.nan,
            )
        position_delta = pd.Series(position).diff().values
        return pd.DataFrame(
            {"boll_position": position, "boll_position_delta": position_delta, "boll_width": width},
            index=df.index,
        )


class SARDeviationFactor(FactorPlugin):
    """SAR偏离度变化率因子 — Δ(SAR/close)，趋势跟踪偏离变化。

    SAR原始值是价格跟踪值，无截面可比性。
    SAR/close 是偏离度，Δ(SAR/close) 是偏离度变化率——趋势转向信号。
    """

    factor_id: str = "sar_deviation"
    display_name: str = "SAR偏离度变化"
    category: str = "tech_trend"
    group_id: str = "sar"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["high", "low", "close"]
    min_periods: int = 6
    requires_full_history: bool = True

    def __init__(self, acceleration: float = 0.02, maximum: float = 0.2, **kwargs: Any) -> None:
        self.acceleration = acceleration
        self.maximum = maximum
        self.min_periods = 6
        self.params = {"acceleration": acceleration, "maximum": maximum}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        high = df["high"].to_numpy(dtype=np.float64)
        low = df["low"].to_numpy(dtype=np.float64)
        close = df["close"].to_numpy(dtype=np.float64)
        sar = talib.SAR(high, low, acceleration=self.acceleration, maximum=self.maximum)
        deviation = sar / close
        delta = pd.Series(deviation).diff().values
        return pd.DataFrame({self.factor_id: delta}, index=df.index)
