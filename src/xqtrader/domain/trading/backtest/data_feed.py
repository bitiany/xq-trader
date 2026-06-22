"""FactorDataFeed — 将预计算 DataFrame 注入 backtrader 作为 DataFeed。

backtrader 的 PandasData 仅支持标准 OHLCV lines。本模块通过动态创建子类，
为每个因子/指标列添加额外 line，使时序规则表达式可在 next() 内直接引用。

设计原则:
  - 动态创建 PandasData 子类，extra_columns → extra lines
  - 使用 -1 自动匹配列名，缺失列填充 NaN
  - 数据索引转为 datetime（backtrader 要求）
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def create_factor_data_feed_class(extra_columns: list[str]) -> type:
    """动态创建带额外 lines 的 PandasData 子类。

    Args:
        extra_columns: 额外列名列表（因子 ID + 技术指标列名）

    Returns:
        PandasData 子类，包含标准 OHLCV lines + 额外 lines
    """
    import backtrader as bt

    lines = tuple(extra_columns)
    params = tuple((col, -1) for col in extra_columns)

    return type(
        "FactorDataFeed",
        (bt.feeds.PandasData,),
        {
            "lines": lines,
            "params": params,
        },
    )


def create_data_feed(
    df: pd.DataFrame,
    extra_columns: list[str],
    name: str,
) -> Any:
    """创建 FactorDataFeed 实例。

    Args:
        df: 预计算 DataFrame（OHLCV + 因子 + 指标），按 trade_date 索引
        extra_columns: 额外列名列表（因子 ID + 技术指标列名的并集）
        name: 数据名称（通常为 symbol）

    Returns:
        backtrader DataFeed 实例
    """
    import backtrader as bt

    normalized_df = df.copy()
    normalized_df.index = pd.to_datetime(normalized_df.index)

    # 确保所有额外列都存在 — 缺失列预填充 NaN
    # 避免 backtrader 对缺失 line 返回 0.0 而非 NaN
    for col in extra_columns:
        if col not in normalized_df.columns:
            normalized_df[col] = float("nan")

    if not extra_columns:
        data = bt.feeds.PandasData(dataname=normalized_df, name=name)
    else:
        feed_cls = create_factor_data_feed_class(extra_columns)
        data = feed_cls(dataname=normalized_df, name=name)

    data.plotinfo.plot = False
    return data


def collect_extra_columns(factor_data: dict[str, pd.DataFrame]) -> list[str]:
    """收集所有 DataFrame 的额外列名并集（排除标准 OHLCV 列）。

    Args:
        factor_data: {symbol: DataFrame} 预计算数据

    Returns:
        额外列名列表（因子 ID + 技术指标列名）
    """
    standard_columns = {"open", "high", "low", "close", "volume", "amount"}
    all_columns: set[str] = set()
    for df in factor_data.values():
        all_columns.update(df.columns)
    return sorted(all_columns - standard_columns)
