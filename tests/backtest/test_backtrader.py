"""Backtrader 回测测试 — 通过模块化组件组装回测"""

import pytest
import pytest_asyncio
import talib as ta
import pandas as pd

from xqtrader.domain.security.models import Security
from xqtrader.domain.market.models.candlestick import CandlestickDaily
from .strategies import MACD_STRATEGY, MACD_KELLY_STRATEGY, MACD_ATR_STRATEGY, RSI_STRATEGY
from .runner import run_backtest

DEFAULT_SYMBOL = "603993.SH"
START_DATE = "2025-06-01"
END_DATE = "2026-06-30"


# ──────────────────────────────────────────────
# 数据加载
# ──────────────────────────────────────────────

@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def ohlcv_df(app_with_datasource):
    """加载 OHLCV 数据并计算衍生指标，供多个测试共享"""
    items = await Security.get_one_or_none(symbol=DEFAULT_SYMBOL)
    assert items is not None
    items = await CandlestickDaily.filter(symbol=items.symbol, order_by=CandlestickDaily.trade_date.asc())
    assert items is not None and len(items) > 0

    df = pd.DataFrame([item.to_dict() for item in items])
    df = df.drop('data_source', axis=1)

    # MACD 指标
    macd, signal, hist = ta.MACD(df.close, fastperiod=12, slowperiod=26, signalperiod=9)
    df["macd"] = macd
    df["signal"] = signal
    df["hist"] = hist * 2

    # 斜率法：hist 的 5 日差分
    df["hist_slope"] = df["hist"] - df["hist"].shift(5)

    # 面积法：连续同号柱的累积面积
    def _hist_area(window):
        pos = window[window > 0].sum()
        neg = window[window < 0].sum()
        return pos if window.iloc[-1] > 0 else neg

    df["hist_area"] = df["hist"].rolling(5).apply(_hist_area, raw=False)

    # RSI 指标
    df["rsi"] = ta.RSI(df.close, timeperiod=14)

    # ATR 指标
    df["atr"] = ta.ATR(df.high, df.low, df.close, timeperiod=14)

    # 全量计算指标后，按时间窗口截取
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    mask = (df["trade_date"] >= START_DATE) & (df["trade_date"] <= END_DATE)
    df = df.loc[mask].reset_index(drop=True)
    return df


@pytest.mark.asyncio(loop_scope="session")
async def test_ohlcv_factors(ohlcv_df):
    print(ohlcv_df.iloc[-5:])


# ──────────────────────────────────────────────
# 回测测试用例
# ──────────────────────────────────────────────

@pytest.mark.asyncio(loop_scope="session")
async def test_macd_strategy(app_with_datasource, ohlcv_df):
    """MACD 金叉死叉策略回测（默认仓位）"""
    perf = run_backtest(
        ohlcv_df, MACD_STRATEGY,
        symbol=DEFAULT_SYMBOL, start_date=START_DATE, end_date=END_DATE,
    )
    assert perf["num_trades"] > 0, "MACD 策略应产生至少一笔交易"


@pytest.mark.asyncio(loop_scope="session")
async def test_macd_kelly_strategy(app_with_datasource, ohlcv_df):
    """MACD 策略 + 凯利公式仓位管理"""
    perf = run_backtest(
        ohlcv_df, MACD_KELLY_STRATEGY,
        symbol=DEFAULT_SYMBOL, start_date=START_DATE, end_date=END_DATE,
    )
    assert perf["num_trades"] > 0, "MACD 凯利策略应产生至少一笔交易"


@pytest.mark.asyncio(loop_scope="session")
async def test_macd_atr_strategy(app_with_datasource, ohlcv_df):
    """MACD 策略 + ATR 仓位管理"""
    perf = run_backtest(
        ohlcv_df, MACD_ATR_STRATEGY,
        symbol=DEFAULT_SYMBOL, start_date=START_DATE, end_date=END_DATE,
    )
    assert perf["num_trades"] > 0, "MACD ATR策略应产生至少一笔交易"


@pytest.mark.asyncio(loop_scope="session")
async def test_rsi_strategy(app_with_datasource, ohlcv_df):
    """RSI 超买超卖策略回测（表达式规则）"""
    perf = run_backtest(
        ohlcv_df, RSI_STRATEGY,
        symbol=DEFAULT_SYMBOL, start_date=START_DATE, end_date=END_DATE,
    )
    print(f"RSI 策略交易次数: {perf['num_trades']}")
