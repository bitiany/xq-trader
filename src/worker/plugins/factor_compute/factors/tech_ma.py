"""技术均线因子 — MA / EMA。

MA: 简单移动平均线，参数化变体 MA(5/10/20/30/60/120/250)
EMA: 指数移动平均线，参数化变体 EMA(12/26)
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import talib  # type: ignore[import-not-found]

from xqtrader.domain.factor.base import FactorPlugin


class MAFactor(FactorPlugin):
    """简单移动平均线因子。"""

    factor_id: str = ""
    display_name: str = ""
    category: str = "tech_ma"
    group_id: str = "ma"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 5
    requires_full_history: bool = False

    def __init__(self, period: int = 20, **kwargs: Any) -> None:
        self.period = period
        self.factor_id = f"ma_{period}"
        self.display_name = f"MA({period})"
        self.min_periods = period
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].values.astype(float)
        ma = talib.MA(close, timeperiod=self.period)
        return pd.DataFrame({self.factor_id: ma}, index=df.index)


class EMAFactor(FactorPlugin):
    """指数移动平均线因子。"""

    factor_id: str = ""
    display_name: str = ""
    category: str = "tech_ma"
    group_id: str = "ema"
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 12
    requires_full_history: bool = True

    def __init__(self, period: int = 12, **kwargs: Any) -> None:
        self.period = period
        self.factor_id = f"ema_{period}"
        self.display_name = f"EMA({period})"
        self.min_periods = period
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].values.astype(float)
        ema = talib.EMA(close, timeperiod=self.period)
        return pd.DataFrame({self.factor_id: ema}, index=df.index)
