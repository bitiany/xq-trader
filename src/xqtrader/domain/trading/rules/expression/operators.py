"""表达式引擎 — 内置算子"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def op_rank(series: pd.Series) -> pd.Series:
    """截面百分位排名 [0, 1]"""
    return series.rank(pct=True)


def op_zscore(series: pd.Series) -> pd.Series:
    """截面 Z-score 标准化"""
    std = series.std()
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=series.index)
    return (series - series.mean()) / std


def op_percentile(series: pd.Series) -> pd.Series:
    """截面百分位 [0, 100]"""
    return series.rank(pct=True) * 100


def op_delta(series: pd.Series, n: int = 1) -> pd.Series:
    """时序差分: x_t - x_{t-n}"""
    return series.diff(n)


def op_ma(series: pd.Series, n: int = 5) -> pd.Series:
    """时序移动平均"""
    return series.rolling(window=n, min_periods=1).mean()


def op_std(series: pd.Series, n: int = 20) -> pd.Series:
    """时序移动标准差"""
    return series.rolling(window=n, min_periods=1).std()


def op_pct_change(series: pd.Series, n: int = 1) -> pd.Series:
    """时序变化率"""
    return series.pct_change(periods=n)


def op_abs(x: float | pd.Series) -> float | pd.Series:
    """绝对值"""
    return abs(x) if isinstance(x, (int, float)) else x.abs()


def op_log(x: float | pd.Series) -> float | pd.Series:
    """自然对数"""
    if isinstance(x, (int, float)):
        return float(np.log(x)) if x > 0 else float("nan")
    return pd.Series(np.log(x.clip(lower=1e-10)), index=x.index)


def op_sign(x: float | pd.Series) -> float | pd.Series:
    """符号函数"""
    if isinstance(x, (int, float)):
        return float(np.sign(x))
    return pd.Series(np.sign(x), index=x.index)


def op_max(a: float, b: float) -> float:
    """取大"""
    return max(a, b)


def op_min(a: float, b: float) -> float:
    """取小"""
    return min(a, b)


def op_cross_above(series_a: pd.Series, series_b: pd.Series | float) -> bool:
    """序列 A 上穿 B：前一日 A < B，当日 A >= B"""
    if len(series_a) < 2:
        return False
    if isinstance(series_b, (int, float)):
        prev_a = float(series_a.iloc[-2])
        curr_a = float(series_a.iloc[-1])
        return bool(prev_a < series_b and curr_a >= series_b)
    if len(series_b) < 2:
        return False
    return bool(
        float(series_a.iloc[-2]) < float(series_b.iloc[-2])
        and float(series_a.iloc[-1]) >= float(series_b.iloc[-1])
    )


def op_cross_below(series_a: pd.Series, series_b: pd.Series | float) -> bool:
    """序列 A 下穿 B：前一日 A > B，当日 A <= B"""
    if len(series_a) < 2:
        return False
    if isinstance(series_b, (int, float)):
        prev_a = float(series_a.iloc[-2])
        curr_a = float(series_a.iloc[-1])
        return bool(prev_a > series_b and curr_a <= series_b)
    if len(series_b) < 2:
        return False
    return bool(
        float(series_a.iloc[-2]) > float(series_b.iloc[-2])
        and float(series_a.iloc[-1]) <= float(series_b.iloc[-1])
    )


# 算子注册表：name → (function, is_cross_section, min_args, max_args)
OPERATOR_REGISTRY: dict[str, tuple[Any, bool, int, int]] = {
    # 截面算子
    "rank": (op_rank, True, 1, 1),
    "zscore": (op_zscore, True, 1, 1),
    "percentile": (op_percentile, True, 1, 1),
    # 时序算子
    "delta": (op_delta, False, 1, 2),
    "ma": (op_ma, False, 1, 2),
    "std": (op_std, False, 1, 2),
    "pct_change": (op_pct_change, False, 1, 2),
    # 通用算子
    "abs": (op_abs, False, 1, 1),
    "log": (op_log, False, 1, 1),
    "sign": (op_sign, False, 1, 1),
    "max": (op_max, False, 2, 2),
    "min": (op_min, False, 2, 2),
    # 交叉算子
    "cross_above": (op_cross_above, False, 2, 2),
    "cross_below": (op_cross_below, False, 2, 2),
}
