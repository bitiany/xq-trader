"""申万行业日线行情增量采集 Stage — 按日期采集全市场申万行业日线行情数据。

执行流程：
  1. 确定日期范围 [start_date, end_date]
  2. 获取交易日列表
  3. 逐日执行：采集 → 清洗 → 持久化 → 更新标的水位

Tushare sw_daily 接口支持按 trade_date 查询全市场数据（单次 ≤ 4000 条），
申万行业约 400+ 个，单日数据远低于上限，无需分页补采。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from framework.commons.logger import get_logger
from framework.commons.utils.data_converter import DataFrameToModelConverter
from xqtrader.broker.services.tushare_data_collector import TushareDataCollector
from xqtrader.domain.sector.models.sw_daily import SwDaily
from xqtrader.domain.watermark.models.collect_watermark import CollectWatermark
from xqtrader.domain.watermark.models.trade_calendar import DEFAULT_TRADE_EXCHANGE, TradeCalendar

logger = get_logger(__name__)

_collector = TushareDataCollector()

_DATA_TYPE = "sw_daily"

# 持久化配置
_NUMERIC_COLS = [
    "open", "close", "high", "low", "change", "pct_change",
    "vol", "amount", "pe", "pb", "float_mv", "total_mv",
]

_PERSIST_UPDATE_FIELDS = _NUMERIC_COLS + ["name", "source"]

_PERSIST_CUSTOM_TRANSFORMS = {
    "trade_date": lambda v: date.fromisoformat(str(v)) if v and str(v) != "nan" else None,
}


def clean_sw_daily_data(df: pd.DataFrame) -> pd.DataFrame:
    """申万行业日线数据清洗。

    1. 删除 trade_date 为空
    2. 数值列强制转 numeric
    3. OHLC 负值置 NaN，bfill + ffill
    4. vol/amount 缺失填充 0
    5. 数值列精度 4 位小数
    6. 删除 close 为 NaN 的行
    """
    ohlc_cols = ["open", "close", "high", "low"]

    # 1. 删除 trade_date 为空
    df = df.dropna(subset=["trade_date"])
    if df.empty:
        return df

    # 2. 数值列强制转 numeric
    for col in _NUMERIC_COLS:
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

    # 4. vol/amount 填充 0
    if "vol" in df.columns:
        df["vol"] = df["vol"].fillna(0)
    if "amount" in df.columns:
        df["amount"] = df["amount"].fillna(0)

    # 5. 数值列精度
    for col in _NUMERIC_COLS:
        if col in df.columns:
            df[col] = df[col].round(4)

    # 6. 删除 close 为 NaN 的行
    if "close" in df.columns:
        df = df.dropna(subset=["close"])

    return df.reset_index(drop=True)


async def persist_sw_daily_data(df: pd.DataFrame) -> int:
    """将申万行业日线数据 upsert 到 SwDaily 表。

    Tushare 返回 ts_code 列，SwDaily 主键使用 ts_code，无需重命名。
    trade_date 格式转换：YYYYMMDD → YYYY-MM-DD。
    """
    df = df.copy()

    # trade_date 格式转换
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


class SwDailyIncrementalStage:
    """申万行业日线行情增量采集 Stage — 按日期采集全市场申万行业日线行情数据。"""

    DATA_TYPE = _DATA_TYPE

    async def execute(self, start_date: date, end_date: date) -> dict[str, Any]:
        """执行增量采集。

        Args:
            start_date: 增量起始日期（含）
            end_date: 增量结束日期（含）

        Returns:
            执行结果汇总
        """
        # 获取交易日列表
        trade_dates = await self._get_trade_dates(start_date, end_date)
        if not trade_dates:
            logger.info("[sw_daily.incremental] 无交易日: %s~%s", start_date, end_date)
            return {"total": 0, "succeeded": 0, "failed": 0, "persisted": 0}

        # 获取标的级水位
        watermark_map = await self._get_watermark_map()
        logger.info(
            "[sw_daily.incremental] 开始: range=%s~%s trade_days=%d",
            start_date, end_date, len(trade_dates),
        )

        total = len(trade_dates)
        succeeded = 0
        failed = 0
        total_persisted = 0

        for idx, td in enumerate(trade_dates, 1):
            try:
                persisted = await self._process_trade_date(td, watermark_map)
                succeeded += 1
                total_persisted += persisted
            except Exception as e:
                failed += 1
                logger.error(
                    "[sw_daily.incremental] 日期 %s 失败: %s",
                    td, e, exc_info=True,
                )

            if idx % 5 == 0 or idx == total:
                logger.info(
                    "[sw_daily.incremental] 进度: %d/%d days succeeded=%d failed=%d persisted=%d",
                    idx, total, succeeded, failed, total_persisted,
                )

        logger.info(
            "[sw_daily.incremental] 完成: range=%s~%s days=%d succeeded=%d failed=%d persisted=%d",
            start_date, end_date, total, succeeded, failed, total_persisted,
        )
        return {"total": total, "succeeded": succeeded, "failed": failed, "persisted": total_persisted}

    async def _process_trade_date(
        self,
        td: date,
        watermark_map: dict[str, date],
    ) -> int:
        """处理单个交易日：采集→清洗→持久化→更新标的水位。"""
        td_str = td.strftime("%Y%m%d")

        # 采集
        df = await _collector.fetch_sw_daily(trade_date=td_str)
        if df is None or df.empty:
            return 0

        # 清洗
        df = clean_sw_daily_data(df)
        if df.empty:
            return 0

        # 按标的水位过滤
        if "ts_code" in df.columns and watermark_map:
            codes_to_update = [c for c, wm in watermark_map.items() if td > wm]
            if codes_to_update:
                df = df[df["ts_code"].isin(codes_to_update)]
            if df.empty:
                return 0

        # 持久化
        df["source"] = "tushare"
        count = await persist_sw_daily_data(df)

        # 更新标的级水位
        if count > 0 and "ts_code" in df.columns:
            updated_codes: list[str] = []
            max_dates: list[date] = []
            for code in df["ts_code"].unique():
                updated_codes.append(code)
                max_dates.append(td)
            if updated_codes:
                await self._batch_update_item_watermarks(updated_codes, max_dates)

        return count

    @staticmethod
    async def _get_trade_dates(start_date: date, end_date: date) -> list[date]:
        """获取日期范围内的交易日列表。"""
        rows = await TradeCalendar.filter(
            exchange=DEFAULT_TRADE_EXCHANGE,
            is_open=True,
            cal_date__gte=start_date,
            cal_date__lte=end_date,
            order_by=TradeCalendar.cal_date.asc(),
        )
        return [row.cal_date for row in rows]

    @staticmethod
    async def _get_watermark_map() -> dict[str, date]:
        """获取标的级水位映射 {ts_code: watermark_date}。"""
        rows = await CollectWatermark.filter(data_type=_DATA_TYPE, status="active")
        return {row.watermark_code: row.watermark_date for row in rows if row.watermark_date is not None}

    @staticmethod
    async def _batch_update_item_watermarks(codes: list[str], max_dates: list[date]) -> None:
        """批量更新标的级水位（使用 bulk_create_or_update）。"""
        instances = [
            CollectWatermark(
                data_type=_DATA_TYPE,
                watermark_code=code,
                watermark_date=max_date,
                record_count=0,
                status="active",
            )
            for code, max_date in zip(codes, max_dates)
        ]
        await CollectWatermark.bulk_create_or_update(
            instances,
            on_conflict=["data_type", "watermark_code"],
            update_fields=["watermark_date"],
        )
