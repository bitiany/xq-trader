"""因子相关去冗余单测。"""

import numpy as np
import pandas as pd

from xqtrader.domain.factor.services.factor_dedup import dedup_by_correlation


def test_dedup_removes_highly_correlated_factor() -> None:
    dates = pd.date_range("2024-01-01", periods=30, freq="B")
    symbols = [f"s{i:03d}" for i in range(40)]
    idx = pd.MultiIndex.from_product([dates, symbols], names=["trade_date", "symbol"])

    rng = np.random.default_rng(0)
    base = rng.normal(size=len(idx))
    # 近乎完全共线，确保平均相关 > 0.9
    panel = pd.DataFrame(
        {"f_high_icir": base, "f_low_icir": base * 1.0001 + rng.normal(scale=1e-6, size=len(idx))},
        index=idx,
    )

    selected = dedup_by_correlation(
        ["f_high_icir", "f_low_icir"],
        panel,
        icir_rank={"f_high_icir": 1.2, "f_low_icir": 0.3},
        threshold=0.9,
        min_periods=20,
    )
    assert selected == ["f_high_icir"]
