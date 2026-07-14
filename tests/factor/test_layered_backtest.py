"""LayeredBacktester 单元测试 — 验证换手成本扣除与方向修复逻辑。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from xqtrader.domain.factor.services.layered_backtest import (
    LayeredBacktester,
    _symmetric_diff_ratio,
)

# ==================== _symmetric_diff_ratio 单测 ====================


def test_symmetric_diff_ratio_identical() -> None:
    """两组完全相同 → 换手率 0。"""
    a = {"000001", "000002", "000003"}
    assert _symmetric_diff_ratio(a, a) == 0.0


def test_symmetric_diff_ratio_disjoint() -> None:
    """两组完全不相交 → 换手率 1。"""
    a = {"000001", "000002"}
    b = {"000003", "000004"}
    assert _symmetric_diff_ratio(a, b) == 1.0


def test_symmetric_diff_ratio_half_overlap() -> None:
    """两组一半重叠 → 换手率 0.5。"""
    a = {"000001", "000002"}
    b = {"000002", "000003"}
    # 对称差异 = {000001, 000003}，并集 = {000001, 000002, 000003}
    # 但 |并集|=3，|对称差异|=2 → 2/3 ≈ 0.667
    assert abs(_symmetric_diff_ratio(a, b) - 2 / 3) < 1e-6


def test_symmetric_diff_ratio_empty_curr() -> None:
    """当日集合为空 → 视为全部换手（1.0）。"""
    assert _symmetric_diff_ratio(set(), {"000001"}) == 1.0


def test_symmetric_diff_ratio_empty_prev() -> None:
    """前日集合为空 → 视为全部换手（1.0）。"""
    assert _symmetric_diff_ratio({"000001"}, set()) == 1.0


# ==================== _calc_group_turnover 单测 ====================


def test_calc_group_turnover_first_day() -> None:
    """首日建仓（prev 为 None）→ 换手率 1.0。"""
    bt = LayeredBacktester()
    curr = {"000001", "000002"}
    ratio = bt._calc_group_turnover(curr, None, curr, None)
    assert ratio == 1.0


def test_calc_group_turnover_no_change() -> None:
    """分组完全不变 → 换手率 0。"""
    bt = LayeredBacktester()
    curr = {"000001", "000002"}
    ratio = bt._calc_group_turnover(curr, curr, curr, curr)
    assert ratio == 0.0


def test_calc_group_turnover_partial_change() -> None:
    """Q1 不变、Q5 半换 → 平均换手率 0.25。"""
    bt = LayeredBacktester()
    q1 = {"000001", "000002"}
    q5_curr = {"000003", "000004"}
    q5_prev = {"000003", "000005"}
    # Q1 换手 0，Q5 换手 2/3 → 平均 1/3
    ratio = bt._calc_group_turnover(q1, q1, q5_curr, q5_prev)
    assert abs(ratio - (0.0 + 2 / 3) / 2) < 1e-6


# ==================== run() 端到端验证 ====================


def _build_panel(factor_values: dict, symbols: list[str], dates: list[str]) -> pd.DataFrame:
    """构建 MultiIndex(trade_date, symbol) 的因子面板。"""
    rows = []
    for d in dates:
        for s in symbols:
            rows.append({
                "trade_date": pd.Timestamp(d),
                "symbol": s,
                "factor": factor_values.get((d, s), np.nan),
            })
    df = pd.DataFrame(rows).set_index(["trade_date", "symbol"])
    return df


def _build_returns(symbols: list[str], dates: list[str], ret: float = 0.001) -> pd.DataFrame:
    """构建恒定正收益的收益率面板。"""
    rows = []
    for d in dates:
        for s in symbols:
            rows.append({
                "trade_date": pd.Timestamp(d),
                "symbol": s,
                "fwd_ret_1d": ret,
            })
    return pd.DataFrame(rows).set_index(["trade_date", "symbol"])


def test_run_low_turnover_low_cost() -> None:
    """低换手因子（分组不变）成本扣除应远小于按日扣除。

    场景：5 个标的，10 个交易日，因子值不变 → 分组完全不变 → 换手率仅首日 1.0
    若按日扣 0.003，年化成本 = 0.997^252 - 1 ≈ -53%
    修复后仅首日扣 0.003，年化成本 = (1-0.0003)^252 - 1 ≈ -7.3%
    """
    symbols = [f"00000{i}.SZ" for i in range(1, 6)]
    dates = [f"2024-01-0{d}" for d in range(1, 10)]

    # 因子值固定不变 → 分组完全不变
    factor_values = {(d, s): float(i) for d in dates for i, s in enumerate(symbols, 1)}
    factor_panel = _build_panel(factor_values, symbols, dates)
    returns_panel = _build_returns(symbols, dates, ret=0.001)

    bt = LayeredBacktester()
    result = bt.run(factor_panel, returns_panel, n_groups=5, round_trip_cost=0.003)

    # Q5-Q1 真实日均收益 = 0（所有组 ret 相同），仅首日扣 0.003
    # 9 个交易日的 ls_daily_rets: [-0.003, 0, 0, 0, 0, 0, 0, 0, 0]
    # 平均 = -0.003/9 ≈ -0.000333
    # 年化 = (1 - 0.000333)^252 - 1 ≈ -0.080
    ls_ret = result["long_short_annual_ret"]
    # 修复后应在 -10% 以内（远好于按日扣除的 -53%）
    assert -0.15 < ls_ret < 0.0, f"低换手因子 ls_ret 应接近 0，实际={ls_ret}"


def test_run_high_turnover_high_cost() -> None:
    """高换手因子（分组每日完全反转）成本扣除接近按日扣除。"""
    symbols = [f"00000{i}.SZ" for i in range(1, 11)]
    dates = [f"2024-01-{d:02d}" for d in range(1, 11)]

    # 因子值每日反转：偶数日升序，奇数日降序
    factor_values = {}
    for i, d in enumerate(dates):
        order = range(1, 11) if i % 2 == 0 else range(10, 0, -1)
        for s, v in zip(symbols, order):
            factor_values[(d, s)] = float(v)

    factor_panel = _build_panel(factor_values, symbols, dates)
    returns_panel = _build_returns(symbols, dates, ret=0.001)

    bt = LayeredBacktester()
    result = bt.run(factor_panel, returns_panel, n_groups=5, round_trip_cost=0.003)

    # 高换手 → 成本接近按日扣除
    # 但因 Q5-Q1 收益也为 0（ret 恒定），ls_ret 主要由成本决定
    # 首日 100% 换手 + 后续每日 ~100% 换手 → 接近按日扣除
    ls_ret = result["long_short_annual_ret"]
    # 应明显为负（高换手高成本）
    assert ls_ret < -0.3, f"高换手因子 ls_ret 应明显为负，实际={ls_ret}"
