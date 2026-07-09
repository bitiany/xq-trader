"""神奇九转 TD Sequential 信号计算 — 基于 OHLCV 数据实时计算反转计数与买卖信号

TD Setup 经典规则:
  买入信号: 连续 9 个交易日收盘价 < 4 日前收盘价（下跌动能衰竭）
  卖出信号: 连续 9 个交易日收盘价 > 4 日前收盘价（上涨动能衰竭）

计数中断条件:
  - 连续计数中断后归零，重新开始
  - 第 9 根 K 线确认后产生信号

输出信号:
  td_seq_buy:    1.0=买入信号触发, 0.0=否
  td_seq_sell:   1.0=卖出信号触发, 0.0=否
  td_seq_count:  正数=上涨计数(卖出预警), 负数=下跌计数(买入预警)

本模块为 OnDemandComputeRegistry 提供 on_demand 因子的纯计算实现，
与 chanlun_signal.compute_chanlun_signals 接口风格一致（输入 OHLCV → 输出 DataFrame）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_td_sequential_signals(df: pd.DataFrame) -> pd.DataFrame:
    """计算神奇九转 TD Sequential 信号

    Args:
        df: OHLCV DataFrame, 必须包含 close 列

    Returns:
        DataFrame with columns: td_seq_buy, td_seq_sell, td_seq_count
        （index 与输入 df 对齐）
    """
    n = len(df)
    buy_signal = np.zeros(n)
    sell_signal = np.zeros(n)
    td_count = np.zeros(n)

    if n < 9:
        return pd.DataFrame(
            {
                "td_seq_buy": buy_signal,
                "td_seq_sell": sell_signal,
                "td_seq_count": td_count,
            },
            index=df.index,
        )

    close = df["close"].astype(float)
    # close.shift(4) — 4 日前收盘价
    close_prev4 = close.shift(4)

    up_count = 0    # 连续 close > close.shift(4) 的天数（卖出预警）
    down_count = 0  # 连续 close < close.shift(4) 的天数（买入预警）

    for i in range(4, n):
        curr = close.iloc[i]
        prev4 = close_prev4.iloc[i]
        if pd.isna(curr) or pd.isna(prev4):
            td_count[i] = up_count if up_count > 0 else -down_count
            continue

        if curr > prev4:
            up_count += 1
            down_count = 0
        elif curr < prev4:
            down_count += 1
            up_count = 0
        else:
            # 相等不计数，重置
            up_count = 0
            down_count = 0

        # 第 9 根确认信号
        if up_count == 9:
            sell_signal[i] = 1.0
            # 信号触发后重置计数（避免重复触发）
            up_count = 0
        if down_count == 9:
            buy_signal[i] = 1.0
            down_count = 0

        td_count[i] = up_count if up_count > 0 else -down_count

    return pd.DataFrame(
        {
            "td_seq_buy": buy_signal,
            "td_seq_sell": sell_signal,
            "td_seq_count": td_count,
        },
        index=df.index,
    )
