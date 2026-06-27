"""ICCalculator 多周期 IC 与显著性单测。"""

import numpy as np
import pandas as pd

from xqtrader.domain.factor.services.ic_calculator import ICCalculator


def _make_panel(n_dates: int = 60, n_symbols: int = 50) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range("2024-01-01", periods=n_dates, freq="B")
    symbols = [f"s{i:03d}" for i in range(n_symbols)]
    idx = pd.MultiIndex.from_product([dates, symbols], names=["trade_date", "symbol"])

    rng = np.random.default_rng(42)
    factor_vals = rng.normal(size=len(idx))
    factor_panel = pd.DataFrame({"f1": factor_vals}, index=idx)

    ret_cols = {}
    for h in (1, 5, 10, 20):
        noise = rng.normal(scale=0.01, size=len(idx))
        ret_cols[f"fwd_ret_{h}d"] = factor_vals * 0.02 + noise
    returns_panel = pd.DataFrame(ret_cols, index=idx)
    return factor_panel, returns_panel


def test_calc_ic_significance_positive_ic() -> None:
    ic = pd.Series([0.05] * 50 + [0.04] * 50)
    sig = ICCalculator.calc_ic_significance(ic, window=252)
    assert sig["ic_tstat"] is not None
    assert sig["ic_pvalue"] is not None
    assert sig["ic_tstat"] > 0
    assert sig["ic_pvalue"] < 0.05


def test_calc_multi_horizon_ic() -> None:
    factor_panel, returns_panel = _make_panel()
    result = ICCalculator.calc_multi_horizon_ic(factor_panel, returns_panel, window=40)
    assert "ic_mean_5d" in result
    assert "ic_mean_10d" in result
    assert "ic_mean_20d" in result
    assert result["ic_mean_5d"] is not None
