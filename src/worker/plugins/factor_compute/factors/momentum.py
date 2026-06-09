"""动量因子 — Momentum / Reversal / BarraMomentum / BarraShortTermReversal。"""

from __future__ import annotations

from typing import Any

import pandas as pd

from xqtrader.domain.factor.base import FactorPlugin


class MomentumFactor(FactorPlugin):
    """动量因子 — 过去N日收益率。"""

    factor_id: str = ""
    display_name: str = ""
    category: str = "momentum"
    group_id: str = "momentum"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 5
    requires_full_history: bool = False

    def __init__(self, period: int = 20, **kwargs: Any) -> None:
        self.period = period
        self.factor_id = f"momentum_{period}"
        self.display_name = f"Momentum({period})"
        self.min_periods = period + 1
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        mom = close.pct_change(periods=self.period) * 100
        return pd.DataFrame({self.factor_id: mom.values}, index=df.index)


class ReversalFactor(FactorPlugin):
    """反转因子 — 短期收益率的反向。"""

    factor_id: str = ""
    display_name: str = ""
    category: str = "momentum"
    group_id: str = "reversal"
    direction: str = "ASC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 5
    requires_full_history: bool = False

    def __init__(self, period: int = 5, **kwargs: Any) -> None:
        self.period = period
        self.factor_id = f"reversal_{period}"
        self.display_name = f"Reversal({period})"
        self.min_periods = period + 1
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        ret = close.pct_change(periods=self.period) * 100
        reversal = -ret
        return pd.DataFrame({self.factor_id: reversal.values}, index=df.index)


class BarraMomentumFactor(FactorPlugin):
    """Barra 动量因子 — 过去12个月累计收益（剔除最近1个月）。"""

    factor_id: str = "barra_momentum"
    display_name: str = "Barra动量"
    category: str = "momentum"
    group_id: str = "barra_momentum"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 252
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        ret_12m = close.pct_change(periods=252)
        ret_1m = close.pct_change(periods=21)
        barra_mom = ret_12m - ret_1m
        return pd.DataFrame({self.factor_id: barra_mom.values}, index=df.index)


class BarraShortTermReversalFactor(FactorPlugin):
    """Barra 短期反转因子 — 最近1个月收益率取反。"""

    factor_id: str = "barra_str"
    display_name: str = "Barra短期反转"
    category: str = "momentum"
    group_id: str = "barra_str"
    direction: str = "ASC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 21
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        ret_1m = close.pct_change(periods=21)
        return pd.DataFrame({self.factor_id: (-ret_1m).values}, index=df.index)
