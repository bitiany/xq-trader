"""IndicatorCalculator 单元测试 — 验证各指标计算正确性。

测试策略：
- 使用已知数据集验证 EMA/MA/MACD/RSI/VWAP/TWAP/BOLL/Donchian/TD9
- 边界情况：空数据、数据量不足 warmup 期
- BOLL 方差口径：验证使用总体方差（ddof=0），与 talib.BBANDS 一致
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from xqtrader.domain.market.intraday.indicator_calculator import IndicatorCalculator


def _make_bars(
    n: int,
    base_price: float = 10.0,
) -> list[dict]:
    """构造 n 根测试 K 线，close 等差递增便于验证。"""
    bars = []
    for i in range(n):
        price = base_price + i * 0.1
        bars.append(
            {
                "open": price - 0.05,
                "high": price + 0.2,
                "low": price - 0.2,
                "close": price,
                "volume": 100.0 + i * 10,
                "amount": (100.0 + i * 10) * price * 100,  # 元
            }
        )
    return bars


# ──────────────── EMA ────────────────

class TestEma:
    def test_warmup_returns_none(self):
        """前 period-1 个返回 None。"""
        calc = IndicatorCalculator.from_dicts(_make_bars(5))
        ema = calc.calc_ema(3)
        assert ema[0] is None
        assert ema[1] is None
        assert ema[2] is not None

    def test_sma_initialization(self):
        """第 period 个用 SMA 初始化。"""
        bars = _make_bars(3)
        calc = IndicatorCalculator.from_dicts(bars)
        ema = calc.calc_ema(3)
        expected = (10.0 + 10.1 + 10.2) / 3
        assert ema[2] == pytest.approx(expected)

    def test_recursion(self):
        """后续使用递推公式。"""
        bars = _make_bars(5)
        calc = IndicatorCalculator.from_dicts(bars)
        ema = calc.calc_ema(3)
        multiplier = 2.0 / (3 + 1)
        expected_at_3 = bars[3]["close"] * multiplier + ema[2] * (1 - multiplier)
        assert ema[3] == pytest.approx(expected_at_3)

    def test_insufficient_data(self):
        """数据量不足 period 时全部返回 None。"""
        calc = IndicatorCalculator.from_dicts(_make_bars(2))
        ema = calc.calc_ema(5)
        assert all(v is None for v in ema)


# ──────────────── MACD ────────────────

class TestMacd:
    def test_warmup(self):
        """DIF 在 slow-1 前为 None。"""
        calc = IndicatorCalculator.from_dicts(_make_bars(30))
        dif, dea, macd = calc.calc_macd(12, 26, 9)
        assert all(v is None for v in dif[:25])
        assert dif[25] is not None

    def test_lengths(self):
        """返回三元组长度等于输入。"""
        calc = IndicatorCalculator.from_dicts(_make_bars(50))
        dif, dea, macd = calc.calc_macd()
        assert len(dif) == 50
        assert len(dea) == 50
        assert len(macd) == 50

    def test_macd_formula(self):
        """MACD = (DIF - DEA) * 2。"""
        calc = IndicatorCalculator.from_dicts(_make_bars(50))
        dif, dea, macd = calc.calc_macd()
        for i in range(len(dif)):
            if dif[i] is not None and dea[i] is not None:
                assert macd[i] == pytest.approx((dif[i] - dea[i]) * 2)


# ──────────────── RSI ────────────────

class TestRsi:
    def test_warmup(self):
        """前 period-1 个返回 None。"""
        calc = IndicatorCalculator.from_dicts(_make_bars(20))
        rsi = calc.calc_rsi(14)
        assert all(v is None for v in rsi[:13])
        assert rsi[13] is not None

    def test_all_up_trend(self):
        """持续上涨 RSI 接近 100。"""
        calc = IndicatorCalculator.from_dicts(_make_bars(30))
        rsi = calc.calc_rsi(14)
        assert rsi[-1] is not None
        assert rsi[-1] > 90  # 持续上涨接近超买

    def test_all_down_trend(self):
        """持续下跌 RSI 接近 0。"""
        bars = _make_bars(30)
        bars = [{**b, "close": 20.0 - i * 0.1} for i, b in enumerate(bars)]
        calc = IndicatorCalculator.from_dicts(bars)
        rsi = calc.calc_rsi(14)
        assert rsi[-1] is not None
        assert rsi[-1] < 10


# ──────────────── VWAP ────────────────

class TestVwap:
    def test_cumulative(self):
        """累计 VWAP = cumAmount / (cumVolume * 100)。"""
        bars = _make_bars(5)
        calc = IndicatorCalculator.from_dicts(bars)
        vwap = calc.calc_vwap()
        cum_amount = sum(b["amount"] for b in bars[:3])
        cum_volume = sum(b["volume"] for b in bars[:3]) * 100
        assert vwap[2] == pytest.approx(cum_amount / cum_volume)

    def test_length(self):
        calc = IndicatorCalculator.from_dicts(_make_bars(10))
        vwap = calc.calc_vwap()
        assert len(vwap) == 10


# ──────────────── TWAP ────────────────

class TestTwap:
    def test_cumulative(self):
        """累计 TWAP = 累计 (H+L+C)/3 的等权平均。"""
        bars = _make_bars(5)
        calc = IndicatorCalculator.from_dicts(bars)
        twap = calc.calc_twap()
        typical = [(b["high"] + b["low"] + b["close"]) / 3 for b in bars]
        expected = sum(typical[:3]) / 3
        assert twap[2] == pytest.approx(expected)


# ──────────────── MA ────────────────

class TestMa:
    def test_warmup(self):
        calc = IndicatorCalculator.from_dicts(_make_bars(10))
        ma = calc.calc_ma(5)
        assert all(v is None for v in ma[:4])
        assert ma[4] is not None

    def test_value(self):
        bars = _make_bars(5)
        calc = IndicatorCalculator.from_dicts(bars)
        ma = calc.calc_ma(5)
        expected = sum(b["close"] for b in bars) / 5
        assert ma[4] == pytest.approx(expected)


# ──────────────── BOLL ────────────────

class TestBoll:
    def test_warmup(self):
        calc = IndicatorCalculator.from_dicts(_make_bars(10))
        boll = calc.calc_boll(20, 2.0)
        assert all(v is None for v in boll["upper"])
        assert all(v is None for v in boll["mid"])
        assert all(v is None for v in boll["lower"])

    def test_population_std(self):
        """验证使用总体方差（ddof=0），与 talib.BBANDS 一致。"""
        bars = _make_bars(25)
        calc = IndicatorCalculator.from_dicts(bars)
        boll = calc.calc_boll(20, 2.0)

        closes = pd.Series([b["close"] for b in bars])
        expected_mid = closes.rolling(20, min_periods=20).mean()
        expected_std = closes.rolling(20, min_periods=20).std(ddof=0)

        idx = 24  # 最后一个
        assert boll["mid"][idx] == pytest.approx(expected_mid.iloc[idx])
        assert boll["upper"][idx] == pytest.approx(
            expected_mid.iloc[idx] + 2.0 * expected_std.iloc[idx]
        )
        assert boll["lower"][idx] == pytest.approx(
            expected_mid.iloc[idx] - 2.0 * expected_std.iloc[idx]
        )

    def test_not_sample_std(self):
        """验证不是样本方差（ddof=1）。"""
        bars = _make_bars(25)
        calc = IndicatorCalculator.from_dicts(bars)
        boll = calc.calc_boll(20, 2.0)

        closes = pd.Series([b["close"] for b in bars])
        sample_std = closes.rolling(20, min_periods=20).std(ddof=1)
        pop_std = closes.rolling(20, min_periods=20).std(ddof=0)

        idx = 24
        # 总体方差 != 样本方差（数据非常数）
        assert not math.isclose(pop_std.iloc[idx], sample_std.iloc[idx])
        # boll 应匹配总体方差
        actual_std = (boll["upper"][idx] - boll["mid"][idx]) / 2.0
        assert actual_std == pytest.approx(pop_std.iloc[idx])


# ──────────────── Donchian ────────────────

class TestDonchian:
    def test_warmup(self):
        calc = IndicatorCalculator.from_dicts(_make_bars(10))
        don = calc.calc_donchian(20)
        assert all(v is None for v in don["upper"])
        assert all(v is None for v in don["lower"])

    def test_values(self):
        bars = _make_bars(25)
        calc = IndicatorCalculator.from_dicts(bars)
        don = calc.calc_donchian(5)
        idx = 24
        window = bars[idx - 4 : idx + 1]
        assert don["upper"][idx] == pytest.approx(max(b["high"] for b in window))
        assert don["lower"][idx] == pytest.approx(min(b["low"] for b in window))


# ──────────────── TD9 ────────────────

class TestTd9:
    def test_sell_setup_on_consecutive_up(self):
        """连续上涨产生 sell_setup 计数 1-9。"""
        # close 等差递增 → close[i] > close[i-4] 恒成立
        bars = _make_bars(20)
        calc = IndicatorCalculator.from_dicts(bars)
        td9 = calc.calc_td9()
        # 从 index=4 开始 sell_setup 递增
        sell_values = [v for v in td9["sell_setup"] if v is not None]
        assert sell_values == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
        # 到 9 后停止
        assert all(v is None for v in td9["sell_setup"][13:])
        # buy_setup 全部为 None
        assert all(v is None for v in td9["buy_setup"])

    def test_buy_setup_on_consecutive_down(self):
        """连续下跌产生 buy_setup 计数 1-9。"""
        bars = _make_bars(20)
        bars = [{**b, "close": 20.0 - i * 0.1} for i, b in enumerate(bars)]
        calc = IndicatorCalculator.from_dicts(bars)
        td9 = calc.calc_td9()
        buy_values = [v for v in td9["buy_setup"] if v is not None]
        assert buy_values == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
        assert all(v is None for v in td9["buy_setup"][13:])

    def test_reset_on_equal(self):
        """close == refClose 时归零。"""
        bars = _make_bars(10)
        # 在 index=5 设 close == close[1]（即 index-4 的前 4 根）
        bars[5]["close"] = bars[1]["close"]
        calc = IndicatorCalculator.from_dicts(bars)
        td9 = calc.calc_td9()
        # index=5 时 close[5] == close[1]，归零
        assert td9["sell_setup"][5] is None
        assert td9["buy_setup"][5] is None


# ──────────────── 边界情况 ────────────────

class TestEdgeCases:
    def test_empty(self):
        """空数据所有指标返回空列表。"""
        calc = IndicatorCalculator.from_dicts([])
        assert calc.calc_ema(5) == []
        assert calc.calc_macd() == ([], [], [])
        assert calc.calc_rsi() == []
        assert calc.calc_vwap() == []
        assert calc.calc_twap() == []
        assert calc.calc_ma(5) == []
        boll = calc.calc_boll()
        assert boll["upper"] == []
        don = calc.calc_donchian()
        assert don["upper"] == []
        td9 = calc.calc_td9()
        assert td9["buy_setup"] == []

    def test_from_orm_bars(self):
        """from_orm_bars 正确构造。"""

        class FakeBar:
            def __init__(self, i: int):
                self.open = 10.0 + i * 0.1
                self.high = 10.2 + i * 0.1
                self.low = 9.8 + i * 0.1
                self.close = 10.0 + i * 0.1
                self.volume = 100 + i
                self.amount = 1000.0 + i * 10

        bars = [FakeBar(i) for i in range(5)]
        calc = IndicatorCalculator.from_orm_bars(bars)
        ma = calc.calc_ma(3)
        assert ma[2] is not None
        assert ma[2] == pytest.approx((10.0 + 10.1 + 10.2) / 3)
