"""动量因子 — Momentum / Reversal / BarraMomentum / BarraShortTermReversal / CsPctChg / Roc。

因子ID命名遵循 factor-catalog.md 规范：
  - mom_ret5d / mom_20d / mom_60d: 动量收益
  - rev_5d / rev_20d: 反转因子
  - barra_momentum: Barra标准动量（12月剔除近1月）
  - barra_strev: Barra短期反转
  - cs_pct_chg: 当日涨跌幅截面
  - roc_10: 10日变化率
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import talib  # type: ignore[import-not-found]

from xqtrader.domain.factor.base import FactorPlugin


class CsPctChgFactor(FactorPlugin):
    """当日涨跌幅截面因子 — 直接读取 pct_chg。"""

    factor_id: str = "cs_pct_chg"
    display_name: str = "当日涨跌幅"
    category: str = "momentum"
    group_id: str = "cs_pct_chg"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 2
    requires_full_history: bool = False

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        pct_chg = close.pct_change() * 100
        return pd.DataFrame({self.factor_id: pct_chg.values}, index=df.index)


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
        self.factor_id = f"mom_ret{period}d" if period <= 5 else f"mom_{period}d"
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
        self.factor_id = f"rev_{period}d"
        self.display_name = f"Reversal({period})"
        self.min_periods = period + 1
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        ret = close.pct_change(periods=self.period) * 100
        reversal = -ret
        return pd.DataFrame({self.factor_id: reversal.values}, index=df.index)


class BarraMomentumFactor(FactorPlugin):
    """Barra 动量因子 — 过去12个月累计收益（剔除最近1个月）。

    标准定义：close[t-21] / close[t-252] - 1
    即从252个交易日前到21个交易日前的收益率，剔除最近1个月的短期反转效应。
    """

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
        # 12月收益剔除近1月：close[t-21]/close[t-252] - 1
        barra_mom = close.shift(21).pct_change(periods=252 - 21)
        return pd.DataFrame({self.factor_id: barra_mom.values}, index=df.index)


class BarraShortTermReversalFactor(FactorPlugin):
    """Barra 短期反转因子 — 最近1个月收益率取反。"""

    factor_id: str = "barra_strev"
    display_name: str = "Barra短期反转"
    category: str = "momentum"
    group_id: str = "barra_strev"
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


class RocFactor(FactorPlugin):
    """变化率因子 — talib.ROC。"""

    factor_id: str = ""
    display_name: str = ""
    category: str = "momentum"
    group_id: str = "roc"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 10
    requires_full_history: bool = False

    def __init__(self, period: int = 10, **kwargs: Any) -> None:
        self.period = period
        self.factor_id = f"roc_{period}"
        self.display_name = f"ROC({period})"
        self.min_periods = period + 1
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].values.astype(float)
        roc = talib.ROC(close, timeperiod=self.period)
        return pd.DataFrame({self.factor_id: roc}, index=df.index)
