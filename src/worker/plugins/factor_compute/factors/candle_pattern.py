"""E2 K线形态聚合因子 — 形态频次 / 影线占比 / 实体占比。

参照 factor-catalog v6.0：
  - cdl_bull_freq_20: 20日看涨形态频次
  - cdl_bear_freq_20: 20日看跌形态频次
  - cdl_net_score_20: 20日形态净得分
  - cdl_upper_shadow_ratio: 上影线占比均值
  - cdl_lower_shadow_ratio: 下影线占比均值
  - cdl_body_ratio: 实体占比均值

设计原则：
  - 单根K线形态识别为离散信号(归信号层)，此处为形态统计聚合，具有截面可比性
  - 影线/实体占比为连续值，20日滚动均值后截面可比
  - 使用 talib CDL 函数族识别看涨/看跌形态
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import talib  # type: ignore[import-not-found]

from xqtrader.domain.factor.base import FactorPlugin

# talib 看涨形态函数名列表（返回正整数表示看涨信号）
_BULL_CDL_FUNCS: list[str] = [
    "CDL3INSIDE", "CDL3LINESTRIKE", "CDL3OUTSIDE", "CDL3STARSINSOUTH",
    "CDL3WHITESOLDIERS", "CDLABANDONEDBABY", "CDLADVANCEBLOCK",
    "CDLBELTHOLD", "CDLBREAKAWAY", "CDLCLOSINGMARUBOZU",
    "CDLCONCEALBABYSWALL", "CDLCOUNTERATTACK", "CDLDARKCLOUDCOVER",
    "CDLDOJI", "CDLDOJISTAR", "CDLDRAGONFLYDOJI", "CDLENGULFING",
    "CDLEVENINGDOJISTAR", "CDLEVENINGSTAR", "CDLGAPSIDESIDEWHITE",
    "CDLGRAVESTONEDOJI", "CDLHAMMER", "CDLHANGINGMAN",
    "CDLHARAMI", "CDLHARAMICROSS", "CDLHIGHWAVE",
    "CDLHIKKAKE", "CDLHIKKAKEMOD", "CDLHOMINGPIGEON",
    "CDLINVERTEDHAMMER", "CDLKICKING", "CDLKICKINGBYLENGTH",
    "CDLLADDERBOTTOM", "CDLLONGLEGGEDDOJI", "CDLLONGLINE",
    "CDLMARUBOZU", "CDLMATCHINGLOW", "CDLMATHOLD",
    "CDLMORNINGDOJISTAR", "CDLMORNINGSTAR", "CDLONNECK",
    "CDLPIERCING", "CDLRICKSHAWMAN", "CDLRISEFALL3METHODS",
    "CDLSEPARATINGLINES", "CDLSHOOTINGSTAR", "CDLSHORTLINE",
    "CDLSPINNINGTOP", "CDLSTALLEDPATTERN", "CDLSTICKSANDWICH",
    "CDLTAKURI", "CDLTASUKIGAP", "CDLTHRUSTING",
    "CDLTRISTAR", "CDLUNIQUE3RIVER", "CDLUPSIDEGAP2CROWS",
    "CDLXSIDEGAP3METHODS",
]


def _classify_cdl_patterns(
    o: np.ndarray, h: np.ndarray, low: np.ndarray, c: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """遍历 talib CDL 函数，统计每日看涨/看跌形态次数。

    talib CDL 函数返回值约定：
      正整数 = 看涨信号
      负整数 = 看跌信号
      0 = 无信号
    """
    n = len(o)
    bull_count = np.zeros(n, dtype=float)
    bear_count = np.zeros(n, dtype=float)

    for func_name in _BULL_CDL_FUNCS:
        func = getattr(talib, func_name, None)
        if func is None:
            continue
        try:
            result = func(o, h, low, c)
            bull_count += (result > 0).astype(float)
            bear_count += (result < 0).astype(float)
        except Exception:
            continue

    return bull_count, bear_count


class CdlBullFreqFactor(FactorPlugin):
    """20日看涨形态频次因子 — 20日内看涨形态出现次数的滚动求和。"""

    factor_id: str = "cdl_bull_freq_20"
    display_name: str = "20日看涨形态频次"
    category: str = "candle_pattern"
    group_id: str = "cdl_agg"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["open", "high", "low", "close"]
    min_periods: int = 20
    requires_full_history: bool = False
    data_origin: str = "computed"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        o = df["open"].values.astype(float)
        h = df["high"].values.astype(float)
        low_ = df["low"].values.astype(float)
        c = df["close"].values.astype(float)
        bull_count, _ = _classify_cdl_patterns(o, h, low_, c)
        freq = pd.Series(bull_count).rolling(window=20, min_periods=self.min_periods).sum().values
        return pd.DataFrame({self.factor_id: freq}, index=df.index)


class CdlBearFreqFactor(FactorPlugin):
    """20日看跌形态频次因子 — 20日内看跌形态出现次数的滚动求和。"""

    factor_id: str = "cdl_bear_freq_20"
    display_name: str = "20日看跌形态频次"
    category: str = "candle_pattern"
    group_id: str = "cdl_agg"
    direction: str = "ASC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["open", "high", "low", "close"]
    min_periods: int = 20
    requires_full_history: bool = False
    data_origin: str = "computed"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        o = df["open"].values.astype(float)
        h = df["high"].values.astype(float)
        low_ = df["low"].values.astype(float)
        c = df["close"].values.astype(float)
        _, bear_count = _classify_cdl_patterns(o, h, low_, c)
        freq = pd.Series(bear_count).rolling(window=20, min_periods=self.min_periods).sum().values
        return pd.DataFrame({self.factor_id: freq}, index=df.index)


class CdlNetScoreFactor(FactorPlugin):
    """20日形态净得分因子 — (看涨-看跌) / 总次数，截面可比。

    值域 [-1, 1]，正值偏多，负值偏空。
    """

    factor_id: str = "cdl_net_score_20"
    display_name: str = "20日形态净得分"
    category: str = "candle_pattern"
    group_id: str = "cdl_agg"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["open", "high", "low", "close"]
    min_periods: int = 20
    requires_full_history: bool = False
    data_origin: str = "computed"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        o = df["open"].values.astype(float)
        h = df["high"].values.astype(float)
        low_ = df["low"].values.astype(float)
        c = df["close"].values.astype(float)
        bull_count, bear_count = _classify_cdl_patterns(o, h, low_, c)
        bull_sum = pd.Series(bull_count).rolling(window=20, min_periods=self.min_periods).sum()
        bear_sum = pd.Series(bear_count).rolling(window=20, min_periods=self.min_periods).sum()
        total = bull_sum + bear_sum
        net_score = np.where(total != 0, (bull_sum - bear_sum) / total, np.nan)
        return pd.DataFrame({self.factor_id: net_score}, index=df.index)


class CdlUpperShadowRatioFactor(FactorPlugin):
    """上影线占比均值因子 — MA(20, (H-max(O,C))/(H-L))。

    上影线长表示上方抛压重，direction=ASC（上影线占比大偏空）。
    """

    factor_id: str = "cdl_upper_shadow_ratio"
    display_name: str = "上影线占比均值"
    category: str = "candle_pattern"
    group_id: str = "cdl_agg"
    direction: str = "ASC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["open", "high", "low", "close"]
    min_periods: int = 20
    requires_full_history: bool = False
    data_origin: str = "computed"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        o = df["open"].values.astype(float)
        h = df["high"].values.astype(float)
        low_ = df["low"].values.astype(float)
        c = df["close"].values.astype(float)
        body_high = np.maximum(o, c)
        hl_range = h - low_
        # 避免 hl_range=0 时除法产生 RuntimeWarning（涨停/跌停 H==L）
        upper_shadow = np.full_like(hl_range, np.nan, dtype=float)
        mask = hl_range != 0
        upper_shadow[mask] = (h - body_high)[mask] / hl_range[mask]
        ratio = pd.Series(upper_shadow).rolling(window=20, min_periods=self.min_periods).mean().values
        return pd.DataFrame({self.factor_id: ratio}, index=df.index)


class CdlLowerShadowRatioFactor(FactorPlugin):
    """下影线占比均值因子 — MA(20, (min(O,C)-L)/(H-L))。

    下影线长表示下方支撑强，direction=DESC（下影线占比大偏多）。
    """

    factor_id: str = "cdl_lower_shadow_ratio"
    display_name: str = "下影线占比均值"
    category: str = "candle_pattern"
    group_id: str = "cdl_agg"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["open", "high", "low", "close"]
    min_periods: int = 20
    requires_full_history: bool = False
    data_origin: str = "computed"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        o = df["open"].values.astype(float)
        h = df["high"].values.astype(float)
        low_ = df["low"].values.astype(float)
        c = df["close"].values.astype(float)
        body_low = np.minimum(o, c)
        hl_range = h - low_
        # 避免 hl_range=0 时除法产生 RuntimeWarning（涨停/跌停 H==L）
        lower_shadow = np.full_like(hl_range, np.nan, dtype=float)
        mask = hl_range != 0
        lower_shadow[mask] = (body_low - low_)[mask] / hl_range[mask]
        ratio = pd.Series(lower_shadow).rolling(window=20, min_periods=self.min_periods).mean().values
        return pd.DataFrame({self.factor_id: ratio}, index=df.index)


class CdlBodyRatioFactor(FactorPlugin):
    """实体占比均值因子 — MA(20, |C-O|/(H-L+0.001))。

    实体占比大表示趋势明确，direction=DESC。
    """

    factor_id: str = "cdl_body_ratio"
    display_name: str = "实体占比均值"
    category: str = "candle_pattern"
    group_id: str = "cdl_agg"
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["open", "high", "low", "close"]
    min_periods: int = 20
    requires_full_history: bool = False
    data_origin: str = "computed"

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        o = df["open"].values.astype(float)
        h = df["high"].values.astype(float)
        low_ = df["low"].values.astype(float)
        c = df["close"].values.astype(float)
        body = np.abs(c - o)
        hl_range = h - low_ + 0.001
        body_ratio = body / hl_range
        ratio = pd.Series(body_ratio).rolling(window=20, min_periods=self.min_periods).mean().values
        return pd.DataFrame({self.factor_id: ratio}, index=df.index)
