"""技术指标计算器 — 基于 talib 的技术指标封装。

提供常用技术指标的计算，供 FactorPrecomputer 在回测前预计算，
结果作为额外列注入 backtrader DataFeed，供时序规则表达式引用。

支持的指标:
  - ATR (Average True Range) — 真实波幅
  - MA (Moving Average — SMA/EMA/WMA/DEMA/TEMA)
  - MACD (Moving Average Convergence Divergence)
  - RSI (Relative Strength Index)
  - Bollinger Bands — 布林带
  - KDJ (Stochastic Oscillator) — 随机指标

设计原则:
  - 纯计算无 I/O，可被任意环境调用
  - 输入 pandas DataFrame(OHLCV)，输出 pandas DataFrame(指标列)
  - 指标参数可配置，输出列名自动生成或自定义
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, cast

import numpy as np
import pandas as pd
import talib

from framework.commons.logger import get_logger

logger = get_logger(__name__)


def _to_float64(series: pd.Series) -> np.ndarray:
    """将 pandas Series 转为 float64 连续内存 ndarray（talib 要求）。"""
    return np.ascontiguousarray(series.values, dtype=np.float64)


@dataclass
class IndicatorSpec:
    """技术指标规格 — 描述一个待计算的指标。

    Attributes:
        name: 指标名称 — atr/ma/macd/rsi/bollinger/kdj
        params: 指标参数，如 {"period": 14}
        output_columns: 输出列名列表，若为空则自动生成
    """

    name: str
    params: dict[str, Any]
    output_columns: list[str]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> IndicatorSpec:
        """从配置字典构建规格。

        配置格式:
            {"name": "atr", "params": {"period": 14}}
            {"name": "atr", "params": {"period": 14}, "output_columns": ["my_atr"]}
        """
        name = d["name"]
        params = d.get("params", {})
        output_columns = list(d.get("output_columns") or [])
        if not output_columns:
            output_columns = _default_output_columns(name, params)
        return cls(name=name, params=params, output_columns=output_columns)


# 指标名 → 默认输出列名生成函数注册表
_OUTPUT_COLUMNS_REGISTRY: dict[str, Callable[[dict[str, Any]], list[str]]] = {}


def _register_output_columns(name: str) -> Callable[[Callable[[dict[str, Any]], list[str]]], Callable[[dict[str, Any]], list[str]]]:
    """装饰器：注册指标默认输出列名生成函数。"""
    def decorator(fn: Callable[[dict[str, Any]], list[str]]) -> Callable[[dict[str, Any]], list[str]]:
        _OUTPUT_COLUMNS_REGISTRY[name] = fn
        return fn
    return decorator


@_register_output_columns("atr")
def _atr_columns(params: dict[str, Any]) -> list[str]:
    return [f"atr_{int(params.get('period', 14))}"]


@_register_output_columns("ma")
def _ma_columns(params: dict[str, Any]) -> list[str]:
    ma_type = params.get("type", "sma")
    return [f"{ma_type}_{int(params.get('period', 20))}"]


@_register_output_columns("macd")
def _macd_columns(params: dict[str, Any]) -> list[str]:
    return ["macd_dif", "macd_dea", "macd_hist"]


@_register_output_columns("rsi")
def _rsi_columns(params: dict[str, Any]) -> list[str]:
    return [f"rsi_{int(params.get('period', 14))}"]


@_register_output_columns("bollinger")
def _bollinger_columns(params: dict[str, Any]) -> list[str]:
    period = int(params.get("period", 20))
    return [f"bb_upper_{period}", f"bb_middle_{period}", f"bb_lower_{period}"]


@_register_output_columns("kdj")
def _kdj_columns(params: dict[str, Any]) -> list[str]:
    return ["kdj_k", "kdj_d", "kdj_j"]


def _default_output_columns(name: str, params: dict[str, Any]) -> list[str]:
    """根据指标名和参数生成默认输出列名。"""
    generator = _OUTPUT_COLUMNS_REGISTRY.get(name)
    if generator is None:
        msg = f"未知指标: {name}"
        raise ValueError(msg)
    return list(generator(params))


def parse_indicator_specs(configs: list[dict[str, Any]]) -> list[IndicatorSpec]:
    """从配置列表解析指标规格列表。

    Args:
        configs: 指标配置列表，如 [{"name": "atr", "params": {"period": 14}}, ...]

    Returns:
        指标规格列表
    """
    return [IndicatorSpec.from_dict(c) for c in configs]


class TechnicalIndicatorCalculator:
    """技术指标计算器 — 基于 talib 封装，纯计算无 I/O。

    用法:
        specs = parse_indicator_specs([{"name": "atr", "params": {"period": 14}}])
        indicator_df = TechnicalIndicatorCalculator.compute_all(specs, ohlcv_df)
    """

    @staticmethod
    def compute(spec: IndicatorSpec, ohlcv: pd.DataFrame) -> pd.DataFrame:
        """根据规格计算单个指标，返回输出列 DataFrame。"""
        method = getattr(TechnicalIndicatorCalculator, f"_compute_{spec.name}", None)
        if method is None:
            msg = f"不支持的指标: {spec.name}"
            raise ValueError(msg)
        return cast(pd.DataFrame, method(ohlcv, spec.params, spec.output_columns))

    @staticmethod
    def compute_all(
        specs: list[IndicatorSpec],
        ohlcv: pd.DataFrame,
    ) -> pd.DataFrame:
        """批量计算多个指标，返回仅含指标列的 DataFrame。"""
        frames: list[pd.DataFrame] = []
        for spec in specs:
            try:
                indicator_df = TechnicalIndicatorCalculator.compute(spec, ohlcv)
                frames.append(indicator_df)
            except (ValueError, KeyError) as e:
                logger.warning(f"指标计算失败: {spec.name} error={e}")
        if not frames:
            return pd.DataFrame(index=ohlcv.index)
        return cast(pd.DataFrame, pd.concat(frames, axis=1))

    # ==================== 各指标实现 ====================

    @staticmethod
    def _compute_atr(
        ohlcv: pd.DataFrame,
        params: dict[str, Any],
        output_columns: list[str],
    ) -> pd.DataFrame:
        """ATR — 平均真实波幅。"""
        period = int(params.get("period", 14))
        atr = talib.ATR(
            _to_float64(ohlcv["high"]),
            _to_float64(ohlcv["low"]),
            _to_float64(ohlcv["close"]),
            timeperiod=period,
        )
        return pd.DataFrame({output_columns[0]: atr}, index=ohlcv.index)

    @staticmethod
    def _compute_ma(
        ohlcv: pd.DataFrame,
        params: dict[str, Any],
        output_columns: list[str],
    ) -> pd.DataFrame:
        """移动平均线 — 支持 sma/ema/wma/dema/tema。"""
        period = int(params.get("period", 20))
        ma_type = params.get("type", "sma").lower()
        close = _to_float64(ohlcv["close"])

        ma_funcs: dict[str, Any] = {
            "sma": talib.SMA,
            "ema": talib.EMA,
            "wma": talib.WMA,
            "dema": talib.DEMA,
            "tema": talib.TEMA,
        }
        func = ma_funcs.get(ma_type)
        if func is None:
            msg = f"不支持的均线类型: {ma_type}"
            raise ValueError(msg)
        values = func(close, timeperiod=period)
        return pd.DataFrame({output_columns[0]: values}, index=ohlcv.index)

    @staticmethod
    def _compute_macd(
        ohlcv: pd.DataFrame,
        params: dict[str, Any],
        output_columns: list[str],
    ) -> pd.DataFrame:
        """MACD — 指数平滑异同移动平均线。"""
        fast = int(params.get("fast", 12))
        slow = int(params.get("slow", 26))
        signal = int(params.get("signal", 9))
        dif, dea, hist = talib.MACD(
            _to_float64(ohlcv["close"]),
            fastperiod=fast,
            slowperiod=slow,
            signalperiod=signal,
        )
        return pd.DataFrame(
            {
                output_columns[0]: dif,
                output_columns[1]: dea,
                output_columns[2]: hist,
            },
            index=ohlcv.index,
        )

    @staticmethod
    def _compute_rsi(
        ohlcv: pd.DataFrame,
        params: dict[str, Any],
        output_columns: list[str],
    ) -> pd.DataFrame:
        """RSI — 相对强弱指数。"""
        period = int(params.get("period", 14))
        rsi = talib.RSI(_to_float64(ohlcv["close"]), timeperiod=period)
        return pd.DataFrame({output_columns[0]: rsi}, index=ohlcv.index)

    @staticmethod
    def _compute_bollinger(
        ohlcv: pd.DataFrame,
        params: dict[str, Any],
        output_columns: list[str],
    ) -> pd.DataFrame:
        """Bollinger Bands — 布林带。"""
        period = int(params.get("period", 20))
        nbdev = float(params.get("nbdev", 2.0))
        upper, middle, lower = talib.BBANDS(
            _to_float64(ohlcv["close"]),
            timeperiod=period,
            nbdevup=nbdev,
            nbdevdn=nbdev,
        )
        return pd.DataFrame(
            {
                output_columns[0]: upper,
                output_columns[1]: middle,
                output_columns[2]: lower,
            },
            index=ohlcv.index,
        )

    @staticmethod
    def _compute_kdj(
        ohlcv: pd.DataFrame,
        params: dict[str, Any],
        output_columns: list[str],
    ) -> pd.DataFrame:
        """KDJ — 随机指标。

        talib 无直接 KDJ，使用 STOCH 计算 K/D，J = 3K - 2D。
        默认使用 SMA 平滑（中国市场标准 KDJ）。
        """
        fastk_period = int(params.get("fastk_period", 9))
        slowk_period = int(params.get("slowk_period", 3))
        slowd_period = int(params.get("slowd_period", 3))

        k, d = talib.STOCH(
            _to_float64(ohlcv["high"]),
            _to_float64(ohlcv["low"]),
            _to_float64(ohlcv["close"]),
            fastk_period=fastk_period,
            slowk_period=slowk_period,
            slowk_matype=talib.MA_Type.SMA,
            slowd_period=slowd_period,
            slowd_matype=talib.MA_Type.SMA,
        )
        j = 3.0 * k - 2.0 * d
        return pd.DataFrame(
            {output_columns[0]: k, output_columns[1]: d, output_columns[2]: j},
            index=ohlcv.index,
        )
