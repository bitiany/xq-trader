"""日行情增量采集 Stage — 按日期批量采集全市场日行情K线数据。

执行流程：
  1. 确定日期范围 [start_date, end_date]
  2. 全市场标的列表 + 标的级水位
  3. 标的分片，逐片执行：采集 → 清洗 → 持久化 → 更新标的水位
  4. 更新市场级水位
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from framework.commons.logger import get_logger
from framework.commons.utils.data_converter import DataFrameToModelConverter
from xqtrader.broker.services.qmt_data_collector import QmtDataCollector
from xqtrader.domain.market.models.candlestick import CandlestickDaily
from xqtrader.domain.security.models import Security
from xqtrader.domain.watermark.models.collect_watermark import CollectWatermark

logger = get_logger(__name__)

_collector = QmtDataCollector()

# 市场级水位标识
_MARKET_WATERMARK_CODE = "MARKET"
_PIPELINE_NAME = "daily_kline_incremental"
_ITEM_PIPELINE_NAME = "daily_kline"

# 持久化配置
_PERSIST_UPDATE_FIELDS = [
    "open", "close", "high", "low", "volume", "amount",
    "change", "pre_close", "pct_chg", "data_source",
]

_PERSIST_CUSTOM_TRANSFORMS = {
    "trade_date": lambda v: date.fromisoformat(str(v)) if v and str(v) != "nan" else None,
}


def clean_kline_data(df: pd.DataFrame) -> pd.DataFrame:
    """日行情K线数据清洗（9 步）。

    1. 删除 trade_date 为空
    2. 数值列强制转 numeric
    3. OHLC 负值置 NaN，bfill + ffill
    4. volume/amount 缺失填充 0
    5. pre_close 缺失用前日 close 填充
    6. pct_chg 缺失重算
    7. change 用 close.diff() 重算
    8. 数值列精度 4 位小数（volume 除外）
    9. 删除 OHLC 仍有 NaN 的行
    """
    ohlc_cols = ["open", "close", "high", "low"]
    numeric_cols = ["open", "close", "high", "low", "volume", "amount", "change", "pre_close", "pct_chg"]

    # 1. 删除 trade_date 为空
    df = df.dropna(subset=["trade_date"])
    if df.empty:
        return df

    # 2. 数值列强制转 numeric
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 3. OHLC 负值置 NaN，用前后值填充
    existing_ohlc = [c for c in ohlc_cols if c in df.columns]
    if existing_ohlc:
        for col in existing_ohlc:
            df.loc[df[col] < 0, col] = np.nan
        for col in existing_ohlc:
            df[col] = df[col].bfill()
            df[col] = df[col].ffill()

    # 4. volume/amount 填充 0
    if "volume" in df.columns:
        df["volume"] = df["volume"].fillna(0).astype(int)
    if "amount" in df.columns:
        df["amount"] = df["amount"].fillna(0)

    # 5. pre_close 缺失用前日 close 填充
    if "pre_close" in df.columns and "close" in df.columns:
        mask = df["pre_close"].isna()
        if mask.any():
            prev_close = df["close"].shift(1)
            df.loc[mask, "pre_close"] = prev_close[mask]
            if df["pre_close"].isna().iloc[0]:
                df.loc[df.index[0], "pre_close"] = df.iloc[0]["close"]
            df["pre_close"] = df["pre_close"].ffill().bfill()

    # 6. pct_chg 缺失重算
    if "pct_chg" in df.columns and "close" in df.columns and "pre_close" in df.columns:
        mask = df["pct_chg"].isna() & df["pre_close"].notna() & (df["pre_close"] != 0)
        df.loc[mask, "pct_chg"] = (
            (df.loc[mask, "close"] - df.loc[mask, "pre_close"])
            / df.loc[mask, "pre_close"] * 100
        ).round(4)

    # 7. change 重算
    if "change" in df.columns and "close" in df.columns:
        df["change"] = df["close"].diff().round(4)
        df.loc[df.index[0], "change"] = 0.0

    # 8. 数值列精度
    for col in numeric_cols:
        if col in df.columns and col != "volume":
            df[col] = df[col].round(4)

    # 9. 删除 OHLC 仍有 NaN 的行
    if existing_ohlc:
        df = df.dropna(subset=existing_ohlc)

    return df.reset_index(drop=True)


async def persist_kline_data(df: pd.DataFrame) -> int:
    """将日行情K线数据 upsert 到 CandlestickDaily 表。"""
    instances = DataFrameToModelConverter.convert(
        df=df,
        model_class=CandlestickDaily,
        custom_transforms=_PERSIST_CUSTOM_TRANSFORMS,
    )
    if not instances:
        return 0
    return await CandlestickDaily.bulk_create_or_update(
        instances,
        on_conflict=["symbol", "trade_date"],
        update_fields=_PERSIST_UPDATE_FIELDS,
        batch_size=100,
    )


class DailyKlineIncrementalStage:
    """日行情增量采集 Stage — 按日期批量采集全市场日行情K线数据。"""

    PIPELINE_NAME = _PIPELINE_NAME
    MARKET_WATERMARK_CODE = _MARKET_WATERMARK_CODE

    def __init__(self, batch_size: int = 50) -> None:
        self._batch_size = batch_size

    async def execute(self, start_date: date, end_date: date) -> dict[str, Any]:
        """执行增量采集。

        Args:
            start_date: 增量起始日期（含）
            end_date: 增量结束日期（含）

        Returns:
            执行结果汇总
        """
        sd = start_date.strftime("%Y%m%d")
        ed = end_date.strftime("%Y%m%d")

        # 获取全市场标的
        stock_codes = await self._get_all_stock_codes()
        if not stock_codes:
            logger.warning("[kline.incremental] 未找到任何标的代码")
            return {"total": 0, "succeeded": 0, "failed": 0, "persisted": 0}

        # 获取标的级水位
        watermark_map = await self._get_watermark_map()
        logger.info(
            "[kline.incremental] 开始: range=%s~%s stocks=%d batch=%d",
            sd, ed, len(stock_codes), self._batch_size,
        )

        total = 0
        succeeded = 0
        failed = 0
        total_persisted = 0

        # 标的分片
        shards = [stock_codes[i:i + self._batch_size] for i in range(0, len(stock_codes), self._batch_size)]

        for idx, shard in enumerate(shards, 1):
            try:
                persisted = await self._process_shard(shard, sd, ed, watermark_map)
                succeeded += 1
                total_persisted += persisted
            except Exception as e:
                failed += 1
                logger.error(
                    "[kline.incremental] 分片 %d/%d 失败: %s",
                    idx, len(shards), e, exc_info=True,
                )
            total += 1

            if idx % 10 == 0 or idx == len(shards):
                logger.info(
                    "[kline.incremental] 进度: %d/%d shards succeeded=%d failed=%d persisted=%d",
                    idx, len(shards), succeeded, failed, total_persisted,
                )

        # 更新市场级水位（仅在有成功分片时）
        if succeeded > 0:
            await self._update_market_watermark(end_date)

        logger.info(
            "[kline.incremental] 完成: range=%s~%s shards=%d succeeded=%d failed=%d persisted=%d",
            sd, ed, total, succeeded, failed, total_persisted,
        )
        return {"total": total, "succeeded": succeeded, "failed": failed, "persisted": total_persisted}

    async def _process_shard(
        self,
        shard: list[str],
        sd: str,
        ed: str,
        watermark_map: dict[str, date],
    ) -> int:
        """处理单个分片：采集→清洗→持久化→更新标的水位。"""
        # 采集
        raw = await _collector.fetch_kline_daily(
            stock_list=shard,
            start_time=sd,
            end_time=ed,
        )

        total_persisted = 0
        updated_codes: list[str] = []
        max_dates: list[date] = []

        for code, df in raw.items():
            if df is None or df.empty:
                continue

            # 清洗
            df = clean_kline_data(df)
            if df.empty:
                continue

            # 按标的水位过滤（只持久化水位日期之后的数据）
            wm_date = watermark_map.get(code)
            if wm_date is not None:
                trade_dates = df["trade_date"].map(lambda v: date.fromisoformat(str(v)))
                df = df[trade_dates > wm_date]
                if df.empty:
                    continue

            # 持久化
            df["symbol"] = code
            df["data_source"] = "qmt"
            count = await persist_kline_data(df)
            total_persisted += count

            # 记录需要更新水位的标的
            if count > 0:
                updated_codes.append(code)
                max_dates.append(df["trade_date"].map(lambda v: date.fromisoformat(str(v))).max())

        # 批量更新标的级水位
        if updated_codes:
            await self._batch_update_item_watermarks(updated_codes, max_dates)

        return total_persisted

    @staticmethod
    async def _get_all_stock_codes() -> list[str]:
        """获取全市场 A 股标的代码。"""
        rows = await Security.filter(
            list_status="L",
            order_by=Security.symbol.asc(),
        )
        return [row.symbol for row in rows]

    @staticmethod
    async def _get_watermark_map() -> dict[str, date]:
        """获取标的级水位映射 {code: watermark_date}。"""
        rows = await CollectWatermark.filter(pipeline_name=_ITEM_PIPELINE_NAME, status="active")
        return {row.watermark_code: row.watermark_date for row in rows if row.watermark_date is not None}

    @staticmethod
    async def _batch_update_item_watermarks(codes: list[str], max_dates: list[date]) -> None:
        """批量更新标的级水位（使用 bulk_create_or_update）。"""
        instances = [
            CollectWatermark(
                pipeline_name=_ITEM_PIPELINE_NAME,
                watermark_code=code,
                watermark_date=max_date,
                record_count=0,
                status="active",
            )
            for code, max_date in zip(codes, max_dates)
        ]
        await CollectWatermark.bulk_create_or_update(
            instances,
            on_conflict=["pipeline_name", "watermark_code"],
            update_fields=["watermark_date"],
        )

    @staticmethod
    async def _update_market_watermark(end_date: date) -> None:
        """更新市场级水位（使用 bulk_create_or_update）。"""
        instance = CollectWatermark(
            pipeline_name=_PIPELINE_NAME,
            watermark_code=_MARKET_WATERMARK_CODE,
            watermark_date=end_date,
            record_count=0,
            status="active",
        )
        await CollectWatermark.bulk_create_or_update(
            [instance],
            on_conflict=["pipeline_name", "watermark_code"],
            update_fields=["watermark_date"],
        )
