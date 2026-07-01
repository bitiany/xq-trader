"""指数日线清洗与持久化 — market.index_daily_collect 插件内部复用。"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from framework.commons.utils.data_converter import DataFrameToModelConverter
from xqtrader.domain.index.models.index_daily import IndexDaily

_PERSIST_UPDATE_FIELDS = [
    "open", "close", "high", "low", "vol", "amount",
    "change", "pre_close", "pct_chg", "source",
]

_PERSIST_CUSTOM_TRANSFORMS = {
    "trade_date": lambda v: date.fromisoformat(str(v)) if v and str(v) != "nan" else None,
}


def clean_index_kline_data(df: pd.DataFrame) -> pd.DataFrame:
    """指数K线数据清洗。"""
    ohlc_cols = ["open", "close", "high", "low"]
    numeric_cols = ["open", "close", "high", "low", "vol", "amount", "change", "pre_close", "pct_chg"]

    df = df.dropna(subset=["trade_date"])
    if df.empty:
        return df

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    existing_ohlc = [c for c in ohlc_cols if c in df.columns]
    if existing_ohlc:
        for col in existing_ohlc:
            df.loc[df[col] < 0, col] = np.nan
        for col in existing_ohlc:
            df[col] = df[col].bfill()
            df[col] = df[col].ffill()

    if "vol" in df.columns:
        df["vol"] = df["vol"].fillna(0)
    if "amount" in df.columns:
        df["amount"] = df["amount"].fillna(0)

    if "pre_close" in df.columns and "close" in df.columns:
        mask = df["pre_close"].isna()
        if mask.any():
            prev_close = df["close"].shift(1)
            df.loc[mask, "pre_close"] = prev_close[mask]
            if df["pre_close"].isna().iloc[0]:
                df.loc[df.index[0], "pre_close"] = df.iloc[0]["close"]
            df["pre_close"] = df["pre_close"].ffill().bfill()

    if "pct_chg" in df.columns and "close" in df.columns and "pre_close" in df.columns:
        mask = df["pct_chg"].isna() & df["pre_close"].notna() & (df["pre_close"] != 0)
        df.loc[mask, "pct_chg"] = (
            (df.loc[mask, "close"] - df.loc[mask, "pre_close"])
            / df.loc[mask, "pre_close"] * 100
        ).round(4)

    if "change" in df.columns and "close" in df.columns:
        df["change"] = df["close"].diff().round(4)
        df.loc[df.index[0], "change"] = 0.0

    for col in numeric_cols:
        if col in df.columns and col != "vol":
            df[col] = df[col].round(4)

    if existing_ohlc:
        df = df.dropna(subset=existing_ohlc)

    return df.reset_index(drop=True)


async def persist_index_kline_data(df: pd.DataFrame) -> int:
    """将指数K线数据 upsert 到 IndexDaily 表。"""
    if "volume" in df.columns and "vol" not in df.columns:
        df = df.rename(columns={"volume": "vol"})

    instances = DataFrameToModelConverter.convert(
        df=df,
        model_class=IndexDaily,
        custom_transforms=_PERSIST_CUSTOM_TRANSFORMS,
    )
    if not instances:
        return 0
    return await IndexDaily.bulk_create_or_update(
        instances,
        on_conflict=["symbol", "trade_date", "source"],
        update_fields=_PERSIST_UPDATE_FIELDS,
        batch_size=100,
    )
