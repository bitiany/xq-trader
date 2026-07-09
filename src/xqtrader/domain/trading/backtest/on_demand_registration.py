"""on_demand 因子计算 + SPI 插件默认注册入口

由 trading 层向 factor 层的 OnDemandComputeRegistry 注入默认实现，实现依赖反转：
  - factor.services.on_demand_compute_registry 仅定义注册中心（不依赖 trading）
  - 本模块负责把所有 on_demand 计算函数 + 14 个 SPI 插件注册进去

注册内容（docs/factor-system-design.md §5.4 on_demand 白名单 + §19.3 SPI 插件）：
  on_demand 因子（因子库无对应 precomputed，消费时实时计算）:
    - chan_buy_point / chan_sell_point / chan_bi_direction（chanpy）
    - td_seq_buy / td_seq_sell / td_seq_count（自研）
    - donchian_high_20 / donchian_low_10（talib/pandas）
    - close / volume（OHLCV 直取）
    - macd / signal / hist / hist_slope / hist_area（talib MACD，国内 hist=2×(MACD−Signal)）
    - ma_short / ma_long（SMA5 / SMA20）
    - boll_upper / boll_middle / boll_lower（布林带三轨）
    - vol_ma_20 / vol_ratio（20日均量 / 5日量比）
    - mom_10d（10日动量）
    - atr_14（14日 ATR，用于唐奇通道突破强度）
  SPI 插件:
    - ExpressionPlugin / MACDPlugin / KDJPlugin / BollingerPlugin / MACrossPlugin
    - ChanlunPlugin / RSIDivergencePlugin / VolumePricePlugin / ADXTrendPlugin
    - BiasReversalPlugin / VolRatioPlugin / TDSequentialPlugin / MomentumPlugin

命名规范（docs/factor-system-design.md §3.4）:
  因子库已有的 precomputed 因子（rsi_14/bias_6/mom_5d/mom_20d/kdj_k/kdj_d/kdj_j/
  adx_14/adx_plus_di/adx_minus_di/boll_width 等）由 DB 加载，不在本注册表重复计算。
  本注册表仅注册因子库中不存在的战术指标（macd/ma/boll三轨/vol/mom_10d/atr_14 等）。

调用时机：应用启动时调用 `register_default_on_demand_computes()`（幂等）。
"""
from __future__ import annotations

from typing import cast

import numpy as np
import pandas as pd
import talib as ta

from framework.commons.logger import get_logger
from xqtrader.domain.factor.services.on_demand_compute_registry import get_registry
from xqtrader.domain.trading.backtest.plugins import (
    ADXTrendPlugin,
    BiasReversalPlugin,
    BollingerPlugin,
    ChanlunPlugin,
    ExpressionPlugin,
    KDJPlugin,
    MACDPlugin,
    MACrossPlugin,
    MomentumPlugin,
    RSIDivergencePlugin,
    TDSequentialPlugin,
    VolRatioPlugin,
    VolumePricePlugin,
)
from xqtrader.domain.trading.backtest.plugins.chanlun_signal import (
    compute_chanlun_signals,
)
from xqtrader.domain.trading.backtest.plugins.donchian_turtle import (
    DonchianTurtlePlugin,
)
from xqtrader.domain.trading.backtest.plugins.td_sequential_signal import (
    compute_td_sequential_signals,
)

logger = get_logger(__name__)

# on_demand 因子白名单（docs/factor-system-design.md §5.4 + 战术指标扩展）
# 因子库中已有 precomputed 版本的因子（rsi_14/bias_6/mom_5d/mom_20d/kdj_*/adx_14/
# adx_plus_di/adx_minus_di/boll_width）不在此列 — 它们由 DB 加载。
ON_DEMAND_FACTOR_IDS: frozenset[str] = frozenset({
    # §5.4 白名单
    "chan_buy_point", "chan_sell_point", "chan_bi_direction",
    "td_seq_buy", "td_seq_sell", "td_seq_count",
    "donchian_high_20", "donchian_low_10",
    "close", "volume",
    # 战术指标（因子库无 precomputed 版本，SPI 插件依赖）
    "macd", "signal", "hist", "hist_slope", "hist_area",
    "ma_short", "ma_long",
    "boll_upper", "boll_middle", "boll_lower",
    "vol_ma_20", "vol_ratio",
    "mom_10d",
    "atr_14",
})

# SPI 插件类清单（14 个）
_DEFAULT_PLUGINS: tuple[type, ...] = (
    ExpressionPlugin,
    MACDPlugin,
    KDJPlugin,
    BollingerPlugin,
    MACrossPlugin,
    ChanlunPlugin,
    RSIDivergencePlugin,
    VolumePricePlugin,
    ADXTrendPlugin,
    BiasReversalPlugin,
    VolRatioPlugin,
    TDSequentialPlugin,
    MomentumPlugin,
    DonchianTurtlePlugin,
)

_registered = False


def _compute_ohlcv_columns(df: pd.DataFrame) -> pd.DataFrame:
    """close / volume 直接从 OHLCV 直取。"""
    out = pd.DataFrame(index=df.index)
    if "close" in df.columns:
        out["close"] = df["close"].astype(float)
    if "volume" in df.columns:
        out["volume"] = df["volume"].astype(float)
    return out


def _compute_donchian(df: pd.DataFrame) -> pd.DataFrame:
    """唐奇安通道上下轨：donchian_high_20 = 20日最高价最高值；donchian_low_10 = 10日最低价最低值。"""
    out = pd.DataFrame(index=df.index)
    if "high" in df.columns:
        out["donchian_high_20"] = df["high"].astype(float).rolling(20).max()
    if "low" in df.columns:
        out["donchian_low_10"] = df["low"].astype(float).rolling(10).min()
    return out


def _compute_macd(df: pd.DataFrame) -> pd.DataFrame:
    """MACD 指标组：macd / signal / hist / hist_slope / hist_area。

    国内主流机构实现：hist = 2 × (MACD − Signal)。
    """
    out = pd.DataFrame(index=df.index)
    if "close" not in df.columns:
        return out
    close = cast(
        "np.ndarray[tuple[int, ...], np.dtype[np.float64]]",
        df["close"].astype(float).to_numpy(dtype=np.float64),
    )
    macd, signal, hist = ta.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    out["macd"] = macd
    out["signal"] = signal
    out["hist"] = hist * 2  # 国内主流机构实现：hist = 2 * (MACD - Signal)
    out["hist_slope"] = out["hist"] - out["hist"].shift(5)
    out["hist_area"] = out["hist"].rolling(5).apply(_calc_hist_area, raw=False)
    return out


def _compute_ma(df: pd.DataFrame) -> pd.DataFrame:
    """双均线：ma_short = SMA5, ma_long = SMA20。"""
    out = pd.DataFrame(index=df.index)
    if "close" not in df.columns:
        return out
    close = df["close"].astype(float)
    out["ma_short"] = close.rolling(5).mean()
    out["ma_long"] = close.rolling(20).mean()
    return out


def _compute_bollinger(df: pd.DataFrame) -> pd.DataFrame:
    """布林带三轨：middle = SMA20, upper/lower = middle ± 2×std。

    注：boll_width（归一化宽度）在因子库 precomputed，由 DB 加载，此处不重复计算。
    """
    out = pd.DataFrame(index=df.index)
    if "close" not in df.columns:
        return out
    close = df["close"].astype(float)
    middle = close.rolling(20).mean()
    std = close.rolling(20).std()
    out["boll_middle"] = middle
    out["boll_upper"] = middle + 2 * std
    out["boll_lower"] = middle - 2 * std
    return out


def _compute_volume_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """量价指标：vol_ma_20 = 20日均量, vol_ratio = 当日量 / 5日均量。"""
    out = pd.DataFrame(index=df.index)
    if "volume" not in df.columns:
        return out
    vol = df["volume"].astype(float)
    out["vol_ma_20"] = vol.rolling(20).mean()
    vol_ma5 = vol.rolling(5).mean()
    out["vol_ratio"] = vol / vol_ma5.replace(0, np.nan)
    return out


def _compute_mom_10d(df: pd.DataFrame) -> pd.DataFrame:
    """10日动量：mom_10d = close / close.shift(10) - 1。

    注：mom_5d / mom_20d / mom_60d 在因子库 precomputed，由 DB 加载。
    """
    out = pd.DataFrame(index=df.index)
    if "close" not in df.columns:
        return out
    close = df["close"].astype(float)
    out["mom_10d"] = close / close.shift(10) - 1
    return out


def _compute_atr_14(df: pd.DataFrame) -> pd.DataFrame:
    """14日 ATR（绝对值），用于唐奇通道突破强度计算。

    注：因子库有 atr_ratio / natr_14（归一化版本），此处的 atr_14 为绝对值，
    供 DonchianTurtlePlugin 计算突破强度使用。
    """
    out = pd.DataFrame(index=df.index)
    if not {"high", "low", "close"}.issubset(df.columns):
        return out
    high = cast(
        "np.ndarray[tuple[int, ...], np.dtype[np.float64]]",
        df["high"].astype(float).to_numpy(dtype=np.float64),
    )
    low = cast(
        "np.ndarray[tuple[int, ...], np.dtype[np.float64]]",
        df["low"].astype(float).to_numpy(dtype=np.float64),
    )
    close = cast(
        "np.ndarray[tuple[int, ...], np.dtype[np.float64]]",
        df["close"].astype(float).to_numpy(dtype=np.float64),
    )
    out["atr_14"] = ta.ATR(high, low, close, timeperiod=14)
    return out


def _calc_hist_area(window: pd.Series) -> float:
    """计算 hist 柱面积（连续同色柱的累计值）。"""
    pos = window[window > 0].sum()
    neg = window[window < 0].sum()
    return float(pos if window.iloc[-1] > 0 else neg)


def register_default_on_demand_computes() -> None:
    """注册默认 on_demand 因子计算函数与 SPI 插件（幂等）。"""
    global _registered
    if _registered:
        return

    registry = get_registry()

    # ── on_demand 因子计算函数 ──
    # §5.4 白名单
    registry.register_compute(
        factor_ids=["chan_buy_point", "chan_sell_point", "chan_bi_direction"],
        compute_fn=compute_chanlun_signals,
        group_key="chanlun",
    )
    registry.register_compute(
        factor_ids=["td_seq_buy", "td_seq_sell", "td_seq_count"],
        compute_fn=compute_td_sequential_signals,
        group_key="td_sequential",
    )
    registry.register_compute(
        factor_ids=["donchian_high_20", "donchian_low_10"],
        compute_fn=_compute_donchian,
        group_key="donchian",
    )
    registry.register_compute(
        factor_ids=["close", "volume"],
        compute_fn=_compute_ohlcv_columns,
        group_key="ohlcv",
    )
    # 战术指标（因子库无 precomputed 版本）
    registry.register_compute(
        factor_ids=["macd", "signal", "hist", "hist_slope", "hist_area"],
        compute_fn=_compute_macd,
        group_key="macd",
    )
    registry.register_compute(
        factor_ids=["ma_short", "ma_long"],
        compute_fn=_compute_ma,
        group_key="ma",
    )
    registry.register_compute(
        factor_ids=["boll_upper", "boll_middle", "boll_lower"],
        compute_fn=_compute_bollinger,
        group_key="bollinger",
    )
    registry.register_compute(
        factor_ids=["vol_ma_20", "vol_ratio"],
        compute_fn=_compute_volume_indicators,
        group_key="volume",
    )
    registry.register_compute(
        factor_ids=["mom_10d"],
        compute_fn=_compute_mom_10d,
        group_key="mom_10d",
    )
    registry.register_compute(
        factor_ids=["atr_14"],
        compute_fn=_compute_atr_14,
        group_key="atr_14",
    )

    # ── SPI 插件 ──
    for plugin_cls in _DEFAULT_PLUGINS:
        registry.register_plugin(plugin_cls)  # type: ignore[arg-type]

    _registered = True
    logger.info(
        "[on_demand] 默认注册完成: factors=%d plugins=%d",
        len(registry.list_on_demand_factors()),
        len(registry.list_plugins()),
    )


def is_registered() -> bool:
    """是否已完成默认注册（供测试与启动校验）。"""
    return _registered


def reset_default_on_demand_computes() -> None:
    """重置默认注册状态（仅用于测试）。

    与 factor 层的 ``reset_registry()`` 配合使用：
      reset_default_on_demand_computes()  # 重置 _registered 标志
      reset_registry()                    # 重置 registry 单例
    随后 ``register_default_on_demand_computes()`` 才会重新执行完整注册。
    """
    global _registered
    _registered = False
