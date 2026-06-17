"""动量/反转因子 — Momentum / BarraMomentum / BarraShortTermReversal / CsPctChg / Roc。

参照 factor-catalog v5.0：
  - 删除 ReversalFactor（rev_5d/rev_20d 与 mom_5d/mom_20d 完全共线）
  - Barra短期反转(barra_strev)与动量是不同现象，保留
  - 动量因子取收益率形式，已是截面可比

因子ID：
  - cs_pct_chg: 当日涨跌幅截面
  - mom_5d / mom_20d / mom_60d: 动量收益
  - barra_momentum: Barra标准动量（12月剔除近1月）
  - barra_strev: Barra短期反转
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
    """动量因子 — 过去N日收益率，截面可比。"""

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
        self.factor_id = f"mom_{period}d"
        self.display_name = f"{period}日动量"
        self.min_periods = period + 1
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        mom = close.pct_change(periods=self.period)
        return pd.DataFrame({self.factor_id: mom.values}, index=df.index)


class BarraMomentumFactor(FactorPlugin):
    """Barra 动量因子 — 半衰期加权的指数加权累积收益。

    使用 ewm(halflife=126) 对日收益率进行指数加权，累积得到
    过去约12个月的加权收益，剔除近1月的短期反转效应。
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
        ret = close.pct_change()
        # 半衰期加权累积收益：ewm(halflife=126) 对收益率加权求和
        barra_mom = ret.ewm(halflife=126).sum()
        # 剔除近1月（21日）的短期反转效应
        barra_mom = barra_mom - barra_mom.shift(21)
        return pd.DataFrame({self.factor_id: barra_mom.values}, index=df.index)


class BarraShortTermReversalFactor(FactorPlugin):
    """Barra 短期反转因子 — 最近1个月收益率取反。

    与动量是不同现象：动量是中长期趋势延续，短期反转是1月均值回归。
    """

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
    """变化率因子 — talib.ROC，截面可比。"""

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
