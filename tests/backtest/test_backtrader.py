"""Backtrader 回测测试 — 通过模块化组件组装回测"""

import pandas as pd
import pytest
import pytest_asyncio
import talib as ta

from xqtrader.domain.market.models.candlestick import CandlestickDaily
from xqtrader.domain.security.models import Security
from xqtrader.domain.trading.backtest.runner import run_backtest

from .strategies import (
    IC_WEIGHTED_STRATEGY,
    MACD_ATR_STRATEGY,
    MACD_KELLY_STRATEGY,
    MACD_RSI_VOTE_STRATEGY,
    MACD_STRATEGY,
    MULTI_GROUP_STRATEGY,
    MULTI_GROUP_VOTE_STRATEGY,
    RSI_BIAS_AND_STRATEGY,
    RSI_BIAS_WEIGHTED_STRATEGY,
    RSI_STRATEGY,
)

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

    # BIAS 乖离率: (close - MA6) / MA6 * 100
    ma6 = df.close.rolling(6).mean()
    df["bias"] = (df.close - ma6) / ma6 * 100

    # MON_5D 5日动量: close / close.shift(5) - 1
    df["mon_5d"] = df.close / df.close.shift(5) - 1

    # ATR 指标
    df["atr"] = ta.ATR(df.high, df.low, df.close, timeperiod=14)

    # 全量计算指标后，按时间窗口截取
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    mask = (df["trade_date"] >= START_DATE) & (df["trade_date"] <= END_DATE)
    df = df.loc[mask].reset_index(drop=True)
    return df

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


# ──────────────────────────────────────────────
# 多规则融合测试用例
# ──────────────────────────────────────────────

@pytest.mark.asyncio(loop_scope="session")
async def test_rsi_bias_and_strategy(app_with_datasource, ohlcv_df):
    """场景一: RSI + BIAS AND 融合 — 两个因子同时满足才产生信号"""
    perf = run_backtest(
        ohlcv_df, RSI_BIAS_AND_STRATEGY,
        symbol=DEFAULT_SYMBOL, start_date=START_DATE, end_date=END_DATE,
    )
    # AND 融合比单规则更严格，交易次数应较少
    print(f"RSI+BIAS AND 策略交易次数: {perf['num_trades']}")


@pytest.mark.asyncio(loop_scope="session")
async def test_rsi_bias_weighted_strategy(app_with_datasource, ohlcv_df):
    """场景一变体: RSI + BIAS 加权评分融合 — score 加权求和后与阈值比较"""
    perf = run_backtest(
        ohlcv_df, RSI_BIAS_WEIGHTED_STRATEGY,
        symbol=DEFAULT_SYMBOL, start_date=START_DATE, end_date=END_DATE,
    )
    print(f"RSI+BIAS 加权评分策略交易次数: {perf['num_trades']}")


@pytest.mark.asyncio(loop_scope="session")
async def test_macd_rsi_vote_strategy(app_with_datasource, ohlcv_df):
    """场景一变体: MACD + RSI 加权投票融合 — plugin + expression 混合规则"""
    perf = run_backtest(
        ohlcv_df, MACD_RSI_VOTE_STRATEGY,
        symbol=DEFAULT_SYMBOL, start_date=START_DATE, end_date=END_DATE,
    )
    assert perf["num_trades"] > 0, "MACD+RSI 投票策略应产生交易"


@pytest.mark.asyncio(loop_scope="session")
async def test_ic_weighted_strategy(app_with_datasource, ohlcv_df):
    """场景一变体: RSI + BIAS + MON_5D IC 加权融合 — 三因子 IC 加权"""
    perf = run_backtest(
        ohlcv_df, IC_WEIGHTED_STRATEGY,
        symbol=DEFAULT_SYMBOL, start_date=START_DATE, end_date=END_DATE,
    )
    print(f"IC 加权策略交易次数: {perf['num_trades']}")


@pytest.mark.asyncio(loop_scope="session")
async def test_multi_group_strategy(app_with_datasource, ohlcv_df):
    """场景二: 多规则组嵌套 — 反转组(RSI+BIAS AND) + 动量组(MON_5D)，组间 OR"""
    perf = run_backtest(
        ohlcv_df, MULTI_GROUP_STRATEGY,
        symbol=DEFAULT_SYMBOL, start_date=START_DATE, end_date=END_DATE,
    )
    print(f"多规则组(OR)策略交易次数: {perf['num_trades']}")


@pytest.mark.asyncio(loop_scope="session")
async def test_multi_group_vote_strategy(app_with_datasource, ohlcv_df):
    """场景二变体: 多规则组嵌套 — 反转组 + 动量组，组间加权投票"""
    perf = run_backtest(
        ohlcv_df, MULTI_GROUP_VOTE_STRATEGY,
        symbol=DEFAULT_SYMBOL, start_date=START_DATE, end_date=END_DATE,
    )
    print(f"多规则组(加权投票)策略交易次数: {perf['num_trades']}")
