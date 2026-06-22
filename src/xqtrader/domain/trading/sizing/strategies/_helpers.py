"""仓位管理策略共享工具 — OHLCV 数据加载与技术指标计算。"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import talib

from framework.commons.logger import get_logger

logger = get_logger(__name__)

# 预加载额外回看天数（用于波动率/ATR 计算需要历史数据）
_PRELOAD_LOOKBACK_DAYS = 90


async def load_ohlcv(
    symbols: list[str],
    start_date: date,
    end_date: date,
) -> dict[str, pd.DataFrame]:
    """加载多标的 OHLCV 数据。

    Returns:
        {symbol: DataFrame[trade_date, open, high, low, close, volume, amount]}
    """
    from xqtrader.domain.market.models.candlestick import CandlestickDaily

    preload_start = start_date - timedelta(days=_PRELOAD_LOOKBACK_DAYS)
    result: dict[str, pd.DataFrame] = {}

    for symbol in symbols:
        records = await CandlestickDaily.filter(
            symbol=symbol,
            trade_date__gte=preload_start,
            trade_date__lte=end_date,
            order_by=CandlestickDaily.trade_date,
        )
        if not records:
            continue
        rows = [
            {
                "trade_date": r.trade_date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
                "amount": r.amount,
            }
            for r in records
        ]
        df = pd.DataFrame(rows).set_index("trade_date").sort_index()
        result[symbol] = df

    logger.debug(f"OHLCV 加载完成: {len(result)}/{len(symbols)} 只标的有数据")
    return result


def compute_daily_returns(close: pd.Series) -> pd.Series:
    """计算日收益率序列。"""
    return close.pct_change().dropna()


def compute_volatility(returns: pd.Series, window: int = 20) -> float:
    """计算年化波动率。"""
    if len(returns) < 2:
        return 0.0
    return float(returns.tail(window).std() * np.sqrt(252))


def compute_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """计算 ATR 序列（使用 talib）。"""
    return pd.Series(
        talib.ATR(high.values, low.values, close.values, timeperiod=period),
        index=high.index,
    )


def compute_atr_value(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> float:
    """计算最新 ATR 值。"""
    atr_series = compute_atr(high, low, close, period)
    if atr_series.empty or pd.isna(atr_series.iloc[-1]):
        return 0.0
    return float(atr_series.iloc[-1])


def compute_kelly_params(returns: pd.Series) -> tuple[float, float, float]:
    """计算 Kelly 公式参数: (win_rate, avg_win, avg_loss)。

    Returns:
        (win_rate, avg_win, avg_loss) — 胜率, 平均盈利, 平均亏损(正值)
    """
    if returns.empty:
        return 0.5, 0.0, 0.0

    wins = returns[returns > 0]
    losses = returns[returns < 0]
    win_rate = len(wins) / len(returns) if len(returns) > 0 else 0.5
    avg_win = float(wins.mean()) if not wins.empty else 0.0
    avg_loss = float(abs(losses.mean())) if not losses.empty else 0.0
    return win_rate, avg_win, avg_loss
