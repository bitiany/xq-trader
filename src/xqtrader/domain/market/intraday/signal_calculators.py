"""分时信号计算器 — 5 类核心信号策略模式实现

每个计算器负责一类信号的计算逻辑，输入 SignalContext（当日 1m 分钟线序列），
输出 SignalResult（信号方向、强度、原始值）。

设计要点：
- 策略模式：基类 SignalCalculator + 5 个具体实现，通过 CALCULATOR_REGISTRY 注册
- 指标计算统一使用 IndicatorCalculator（接收 OHLCV DataFrame），避免各处重复实现
- 纯计算无副作用：不查库、不推送，仅返回结果；持久化与推送由 IntradaySignalEngine 负责
- 开盘 30 分钟内不触发 VWAP/TWAP 类信号（数据不稳定，业界惯例）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from xqtrader.domain.market.intraday.indicator_calculator import IndicatorCalculator
from xqtrader.domain.market.models.candlestick import CandlestickMinute
from xqtrader.domain.trading.enums import Direction, IntradaySignalType

logger = logging.getLogger("INTRADAY.SIGNAL_CALC")

# ──────────────── 数据结构 ────────────────

@dataclass(frozen=True)
class SignalContext:
    """信号计算上下文

    Attributes:
        symbol: 证券代码，如 600000.SH
        name: 证券名称
        bars: 当日 1m 分钟线序列，按 trade_time 升序
        trade_date: 交易日期
    """
    symbol: str
    name: str
    bars: list[CandlestickMinute]
    trade_date: date


@dataclass(frozen=True)
class SignalResult:
    """信号计算结果

    Attributes:
        signal_type: 信号类型，见 IntradaySignalType
        direction: 方向 long/short/neutral
        strength: 信号强度 0-1
        raw_values: 原始指标值（用于持久化与前端展示）
        trade_time: 信号触发时间（最新 bar 的 trade_time）
    """
    signal_type: str
    direction: str
    strength: float
    raw_values: dict[str, Any]
    trade_time: datetime


# ──────────────── 指标计算 ────────────────
# EMA/MACD/RSI/VWAP/TWAP 统一由 IndicatorCalculator 提供，本模块不再各自实现。

# ──────────────── 信号计算器基类 ────────────────

class SignalCalculator:
    """信号计算器抽象基类

    子类需实现 calculate 方法，返回 SignalResult 或 None（无信号）。
    """
    signal_type: str = ""

    def calculate(self, ctx: SignalContext) -> SignalResult | None:
        """计算信号，返回 SignalResult 或 None"""
        raise NotImplementedError


# ──────────────── 1. VWAP 突破/跌破 ────────────────

class VwapBreakthroughCalculator(SignalCalculator):
    """VWAP 突破/跌破信号

    逻辑：
    - 价格从下方上穿 VWAP → long（突破分水岭，转强）
    - 价格从上方下穿 VWAP → short（跌破分水岭，转弱）
    - 开盘 30 分钟内不触发（数据不稳定）
    """
    signal_type = IntradaySignalType.VWAP_BREAKTHROUGH

    _WARMUP_MINUTES = 30  # 开盘后 30 分钟内不触发

    def calculate(self, ctx: SignalContext) -> SignalResult | None:
        bars = ctx.bars
        if len(bars) < self._WARMUP_MINUTES + 2:
            return None

        calc = IndicatorCalculator.from_orm_bars(bars)
        vwap = calc.calc_vwap()
        # 比较最新一根 bar 与上一根 bar 是否穿越 VWAP
        idx = len(bars) - 1
        prev_close = bars[idx - 1].close
        curr_close = bars[idx].close
        prev_vwap = vwap[idx - 1]
        curr_vwap = vwap[idx]

        crossed_up = prev_close <= prev_vwap and curr_close > curr_vwap
        crossed_down = prev_close >= prev_vwap and curr_close < curr_vwap

        if not (crossed_up or crossed_down):
            return None

        direction = Direction.LONG if crossed_up else Direction.SHORT
        deviation = abs(curr_close - curr_vwap) / curr_vwap if curr_vwap > 0 else 0.0
        strength = min(deviation / 0.02, 1.0)  # 偏离 2% 视为强度 1.0

        return SignalResult(
            signal_type=self.signal_type,
            direction=direction,
            strength=round(strength, 4),
            raw_values={
                "close": curr_close,
                "vwap": round(curr_vwap, 4),
                "deviation_pct": round(deviation * 100, 2),
                "cross": "up" if crossed_up else "down",
            },
            trade_time=bars[idx].trade_time,
        )


# ──────────────── 2. TWAP 偏离预警 ────────────────

class TwapDeviationCalculator(SignalCalculator):
    """TWAP 偏离预警信号

    逻辑：
    - 价格高于 TWAP 超过阈值 → short（超买，可能均值回归）
    - 价格低于 TWAP 超过阈值 → long（超卖，可能均值回归）
    - 开盘 30 分钟内不触发
    """
    signal_type = IntradaySignalType.TWAP_DEVIATION

    _WARMUP_MINUTES = 30
    _DEVIATION_THRESHOLD = 0.02  # 偏离 ±2% 触发

    def calculate(self, ctx: SignalContext) -> SignalResult | None:
        bars = ctx.bars
        if len(bars) < self._WARMUP_MINUTES + 1:
            return None

        calc = IndicatorCalculator.from_orm_bars(bars)
        twap = calc.calc_twap()
        idx = len(bars) - 1
        curr_close = bars[idx].close
        curr_twap = twap[idx]

        if curr_twap <= 0:
            return None

        deviation = (curr_close - curr_twap) / curr_twap
        if abs(deviation) < self._DEVIATION_THRESHOLD:
            return None

        direction = Direction.SHORT if deviation > 0 else Direction.LONG
        strength = min(abs(deviation) / 0.03, 1.0)  # 偏离 3% 视为强度 1.0

        return SignalResult(
            signal_type=self.signal_type,
            direction=direction,
            strength=round(strength, 4),
            raw_values={
                "close": curr_close,
                "twap": round(curr_twap, 4),
                "deviation_pct": round(deviation * 100, 2),
            },
            trade_time=bars[idx].trade_time,
        )


# ──────────────── 3. MACD 金叉/死叉 ────────────────

class MacdCrossCalculator(SignalCalculator):
    """MACD 金叉/死叉信号

    逻辑：
    - DIF 从下方上穿 DEA → long（金叉）
    - DIF 从上方下穿 DEA → short（死叉）
    - 需要至少 slow+signal = 35 根 bar 才能 warmup 完成
    """
    signal_type = IntradaySignalType.MACD_CROSS

    _FAST = 12
    _SLOW = 26
    _SIGNAL = 9
    _MIN_BARS = _SLOW + _SIGNAL  # 35

    def calculate(self, ctx: SignalContext) -> SignalResult | None:
        bars = ctx.bars
        if len(bars) < self._MIN_BARS + 1:
            return None

        calc = IndicatorCalculator.from_orm_bars(bars)
        dif, dea, _ = calc.calc_macd(self._FAST, self._SLOW, self._SIGNAL)

        idx = len(bars) - 1
        prev_dif, prev_dea = dif[idx - 1], dea[idx - 1]
        curr_dif, curr_dea = dif[idx], dea[idx]
        if None in (prev_dif, prev_dea, curr_dif, curr_dea):
            return None

        golden_cross = prev_dif <= prev_dea and curr_dif > curr_dea  # type: ignore[operator]
        death_cross = prev_dif >= prev_dea and curr_dif < curr_dea  # type: ignore[operator]
        if not (golden_cross or death_cross):
            return None

        direction = Direction.LONG if golden_cross else Direction.SHORT
        # 强度由 MACD 柱绝对值衡量（归一化到价格的 1%）
        curr_close = bars[idx].close
        macd_hist = abs((curr_dif - curr_dea) * 2)  # type: ignore[operator]
        strength = min(macd_hist / curr_close / 0.01, 1.0) if curr_close > 0 else 0.0

        return SignalResult(
            signal_type=self.signal_type,
            direction=direction,
            strength=round(strength, 4),
            raw_values={
                "dif": round(curr_dif, 4),  # type: ignore[arg-type]
                "dea": round(curr_dea, 4),  # type: ignore[arg-type]
                "macd_hist": round(macd_hist, 4),
                "cross": "golden" if golden_cross else "death",
            },
            trade_time=bars[idx].trade_time,
        )


# ──────────────── 4. RSI 超买/超卖 ────────────────

class RsiExtremeCalculator(SignalCalculator):
    """RSI 超买/超卖信号

    逻辑：
    - RSI > 70 → short（超买，可能回落）
    - RSI < 30 → long（超卖，可能反弹）
    """
    signal_type = IntradaySignalType.RSI_EXTREME

    _PERIOD = 14
    _OVERBOUGHT = 70.0
    _OVERSOLD = 30.0

    def calculate(self, ctx: SignalContext) -> SignalResult | None:
        bars = ctx.bars
        if len(bars) < self._PERIOD + 1:
            return None

        calc = IndicatorCalculator.from_orm_bars(bars)
        rsi_series = calc.calc_rsi(self._PERIOD)
        idx = len(bars) - 1
        curr_rsi = rsi_series[idx]
        if curr_rsi is None:
            return None

        if curr_rsi > self._OVERBOUGHT:
            direction = Direction.SHORT
            strength = min((curr_rsi - self._OVERBOUGHT) / 30.0, 1.0)
        elif curr_rsi < self._OVERSOLD:
            direction = Direction.LONG
            strength = min((self._OVERSOLD - curr_rsi) / 30.0, 1.0)
        else:
            logger.debug("RSI 未触发: symbol=%s, rsi=%.2f (正常区间)", ctx.symbol, curr_rsi)
            return None

        return SignalResult(
            signal_type=self.signal_type,
            direction=direction,
            strength=round(strength, 4),
            raw_values={
                "rsi": round(curr_rsi, 2),
                "threshold_overbought": self._OVERBOUGHT,
                "threshold_oversold": self._OVERSOLD,
            },
            trade_time=bars[idx].trade_time,
        )


# ──────────────── 5. 量价背离 ────────────────

class VolumePriceDivergenceCalculator(SignalCalculator):
    """量价背离信号

    逻辑（基于最近 N=30 根 bar）：
    - 价格创 N 根新高，但成交量较前 N-1 根最大量萎缩至少 20% -> short（顶背离）
    - 价格创 N 根新低，但成交量较前 N-1 根最小量放大至少 20% -> long（底背离）
    - 价格突破幅度至少 0.3%，避免微小突破的噪音
    """
    signal_type = IntradaySignalType.VOLUME_PRICE_DIVERGENCE

    _WINDOW = 30
    _MIN_PRICE_BREAK = 0.003  # 价格突破至少 0.3%
    _MIN_VOL_RATIO = 0.20     # 量能萎缩/放大至少 20%

    def calculate(self, ctx: SignalContext) -> SignalResult | None:
        bars = ctx.bars
        if len(bars) < self._WINDOW:
            return None

        window = bars[-self._WINDOW:]
        idx = self._WINDOW - 1
        curr_high = window[idx].high
        curr_low = window[idx].low
        curr_vol = window[idx].volume

        prev_highs = [b.high for b in window[:-1]]
        prev_lows = [b.low for b in window[:-1]]
        prev_vols = [b.volume for b in window[:-1]]

        max_prev_high = max(prev_highs)
        min_prev_low = min(prev_lows)
        max_prev_vol = max(prev_vols)
        min_prev_vol = min(prev_vols)

        # 顶背离：价创新高，量萎缩至少 20%
        price_break_up = (curr_high - max_prev_high) / max_prev_high if max_prev_high > 0 else 0.0
        vol_shrink = (max_prev_vol - curr_vol) / max_prev_vol if max_prev_vol > 0 else 0.0
        top_divergence = (price_break_up >= self._MIN_PRICE_BREAK
                         and vol_shrink >= self._MIN_VOL_RATIO)

        # 底背离：价创新低，量放大至少 20%
        price_break_down = (min_prev_low - curr_low) / min_prev_low if min_prev_low > 0 else 0.0
        vol_expand = (curr_vol - min_prev_vol) / min_prev_vol if min_prev_vol > 0 else 0.0
        bottom_divergence = (price_break_down >= self._MIN_PRICE_BREAK
                            and vol_expand >= self._MIN_VOL_RATIO)

        if not (top_divergence or bottom_divergence):
            return None

        direction = Direction.SHORT if top_divergence else Direction.LONG
        # 强度：价突破幅度与量能变化综合衡量
        price_break = price_break_up if top_divergence else price_break_down
        vol_ratio = vol_shrink if top_divergence else vol_expand
        strength = min((price_break + vol_ratio) / 0.05, 1.0)  # 5% 综合偏离视为强度 1.0

        return SignalResult(
            signal_type=self.signal_type,
            direction=direction,
            strength=round(strength, 4),
            raw_values={
                "divergence": "top" if top_divergence else "bottom",
                "curr_high": curr_high,
                "curr_low": curr_low,
                "curr_volume": curr_vol,
                "max_prev_high": max_prev_high,
                "min_prev_low": min_prev_low,
                "max_prev_volume": max_prev_vol,
                "min_prev_volume": min_prev_vol,
            },
            trade_time=bars[-1].trade_time,
        )


# ──────────────── 计算器注册表 ────────────────

CALCULATOR_REGISTRY: dict[str, type[SignalCalculator]] = {
    IntradaySignalType.VWAP_BREAKTHROUGH: VwapBreakthroughCalculator,
    IntradaySignalType.TWAP_DEVIATION: TwapDeviationCalculator,
    IntradaySignalType.MACD_CROSS: MacdCrossCalculator,
    IntradaySignalType.RSI_EXTREME: RsiExtremeCalculator,
    IntradaySignalType.VOLUME_PRICE_DIVERGENCE: VolumePriceDivergenceCalculator,
}


def get_all_calculators() -> list[SignalCalculator]:
    """获取所有已注册的信号计算器实例"""
    return [cls() for cls in CALCULATOR_REGISTRY.values()]
