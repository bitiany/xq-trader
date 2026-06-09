"""收益率因子 — 前向收益率，用于因子评估。

计算 T 日的前向收益率：fwd_ret_nd = close[T+n] / close[T] - 1
跳过预处理（MAD 去极值不适用于收益率）。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from xqtrader.domain.factor.base import FactorPlugin


class ReturnFactor(FactorPlugin):
    """前向收益率因子 — 评估标签，非交易信号。"""

    factor_id: str = ""
    display_name: str = ""
    category: str = "return"
    group_id: str = "return"
    direction: str = "ASC"
    scope: str = "both"
    signal_type: str = "continuous"
    dependencies: list[str] = ["close"]
    min_periods: int = 1
    requires_full_history: bool = False
    skip_preprocess: bool = True
    data_origin: str = "computed"

    def __init__(self, period: int = 1, **kwargs: Any) -> None:
        self.period = period
        self.factor_id = f"fwd_ret_{period}d"
        self.display_name = f"前向{period}日收益率"
        self.min_periods = 1
        self.params = {"period": period}

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        close = df["close"].astype(float)
        fwd_ret = close.shift(-self.period) / close - 1
        return pd.DataFrame({self.factor_id: fwd_ret.values}, index=df.index)
