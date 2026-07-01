"""申万行业日线清洗与持久化 — market.sw_daily_collect 插件内部复用。"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from framework.commons.utils.data_converter import DataFrameToModelConverter
from xqtrader.domain.sector.models.sw_daily import SwDaily

_NUMERIC_COLS = [
    "open", "close", "high", "low", "change", "pct_change",
    "vol", "amount", "pe", "pb", "float_mv", "total_mv",
]

_PERSIST_UPDATE_FIELDS = _NUMERIC_COLS + ["name", "source"]

_PERSIST_CUSTOM_TRANSFORMS = {
    "trade_date": lambda v: date.fromisoformat(str(v)) if v and str(v) != "nan" else None,
}


def clean_sw_daily_data(df: pd.DataFrame) -> pd.DataFrame:
    """申万行业日线数据清洗。"""
    ohlc_cols = ["open", "close", "high", "low"]

    df = df.dropna(subset=["trade_date"])
    if df.empty:
        return df

    for col in _NUMERIC_COLS:
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

    for col in _NUMERIC_COLS:
        if col in df.columns:
            df[col] = df[col].round(4)

    if "close" in df.columns:
        df = df.dropna(subset=["close"])

    return df.reset_index(drop=True)


async def persist_sw_daily_data(df: pd.DataFrame) -> int:
    """将申万行业日线数据 upsert 到 SwDaily 表。"""
    df = df.copy()

    if "trade_date" in df.columns:
        df["trade_date"] = df["trade_date"].map(
            lambda v: f"{str(v)[:4]}-{str(v)[4:6]}-{str(v)[6:8]}" if pd.notna(v) and len(str(v)) == 8 else v
        )

    instances = DataFrameToModelConverter.convert(
        df=df,
        model_class=SwDaily,
        custom_transforms=_PERSIST_CUSTOM_TRANSFORMS,
    )
    if not instances:
        return 0
    return await SwDaily.bulk_create_or_update(
        instances,
        on_conflict=["ts_code", "trade_date", "source"],
        update_fields=_PERSIST_UPDATE_FIELDS,
        batch_size=100,
    )
