"""每日指标增量采集 Stage — 逐日采集全市场每日指标数据。

执行流程：
  1. 确定日期范围 [start_date, end_date]
  2. 获取交易日列表
  3. 逐日执行：采集 → 清洗 → 持久化 → 更新标的水位
  4. 更新市场级水位

数据源：Tushare daily_basic 接口（单次上限 6000 条）。
逐日采集时传入 trade_date 获取全市场当日数据。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from framework.commons.logger import get_logger
from framework.commons.utils.data_converter import DataFrameToModelConverter
from xqtrader.broker.services.tushare_data_collector import TushareDataCollector
from xqtrader.domain.market.models.daily_indicator import DailyIndicator
from xqtrader.domain.watermark.models.collect_watermark import CollectWatermark
from xqtrader.domain.watermark.models.trade_calendar import TradeCalendar

logger = get_logger(__name__)

_collector: TushareDataCollector | None = None

# 市场级水位标识
_MARKET_WATERMARK_CODE = "MARKET"
_PIPELINE_NAME = "daily_indicator_incremental"
_ITEM_PIPELINE_NAME = "daily_indicator"

# daily_basic 接口字段 → DailyIndicator 模型字段
_COLUMN_MAPPING: dict[str, str] = {
    "ts_code": "symbol",
}

# 数值列（需要强制转 numeric + 精度处理）
_NUMERIC_COLS = [
    "close", "turnover_rate", "turnover_rate_f", "volume_ratio",
    "pe", "pe_ttm", "pb", "ps", "ps_ttm",
    "dv_ratio", "dv_ttm",
    "total_share", "float_share", "free_share",
    "total_mv", "circ_mv",
    "ev", "ebitda", "ev_ebitda", "peg", "pcf",
]

# 持久化更新字段（与数值列一致）
_PERSIST_UPDATE_FIELDS = _NUMERIC_COLS

_PERSIST_CUSTOM_TRANSFORMS = {
    "trade_date": lambda v: date.fromisoformat(str(v)) if v and str(v) != "nan" else None,
}

# daily_basic 单次上限
_DAILY_BASIC_ROW_LIMIT = 6000


def _get_collector() -> TushareDataCollector:
    """延迟初始化 TushareDataCollector 单例。"""
    global _collector  # noqa: PLW0603
    if _collector is None:
        _collector = TushareDataCollector()
    return _collector


def clean_daily_indicator_data(df: pd.DataFrame) -> pd.DataFrame:
    """每日指标数据清洗 — 列映射 + 格式统一 + 数值处理。

    1. 列名映射（daily_basic → DailyIndicator）
    2. trade_date 格式统一 YYYY-MM-DD
    3. 删除 trade_date/symbol 为空的行
    4. 数值列强制转 numeric
    5. 数值列精度 4 位小数
    """
    # 1. 列名映射
    df = df.rename(columns=_COLUMN_MAPPING)

    # 2. trade_date 格式统一
    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")

    # 3. 删除关键字段为空的行（close 为 NOT NULL 字段）
    df = df.dropna(subset=["symbol", "trade_date", "close"])
    if df.empty:
        return df

    # 4. 数值列强制转 numeric
    for col in _NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 5. 数值列精度
    for col in _NUMERIC_COLS:
        if col in df.columns:
            df[col] = df[col].round(4)

    return df.reset_index(drop=True)


async def persist_daily_indicator_data(df: pd.DataFrame) -> int:
    """将每日指标数据 upsert 到 DailyIndicator 表。"""
    instances = DataFrameToModelConverter.convert(
        df=df,
        model_class=DailyIndicator,
        custom_transforms=_PERSIST_CUSTOM_TRANSFORMS,
    )
    if not instances:
        return 0
    return await DailyIndicator.bulk_create_or_update(
        instances,  # type: ignore[arg-type]
        on_conflict=["symbol", "trade_date"],
        update_fields=_PERSIST_UPDATE_FIELDS,
        batch_size=100,
    )


class DailyIndicatorIncrementalStage:
    """每日指标增量采集 Stage — 逐日采集全市场每日指标数据。"""

    PIPELINE_NAME = _PIPELINE_NAME
    MARKET_WATERMARK_CODE = _MARKET_WATERMARK_CODE

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
            logger.info("[daily_indicator.incremental] 无需采集的交易日")
            return {"total": 0, "succeeded": 0, "failed": 0, "persisted": 0}

        # 获取标的级水位
        watermark_map = await self._get_watermark_map()

        logger.info(
            "[daily_indicator.incremental] 开始: range=%s~%s trade_days=%d",
            start_date, end_date, len(trade_dates),
        )

        total = len(trade_dates)
        succeeded = 0
        failed = 0
        total_persisted = 0
        actual_max_date: date | None = None  # 跟踪实际数据的最新日期

        for idx, td in enumerate(trade_dates, 1):
            try:
                persisted = await self._process_trade_date(td, watermark_map)
                succeeded += 1
                total_persisted += persisted
                if persisted > 0:
                    actual_max_date = td
            except Exception as e:
                failed += 1
                logger.error(
                    "[daily_indicator.incremental] 日期 %s 失败: %s",
                    td, e, exc_info=True,
                )

            if idx % 5 == 0 or idx == total:
                logger.info(
                    "[daily_indicator.incremental] 进度: %d/%d days succeeded=%d failed=%d persisted=%d",
                    idx, total, succeeded, failed, total_persisted,
                )

        # 更新市场级水位（按实际数据的最新日期）
        if actual_max_date is not None:
            await self._update_market_watermark(actual_max_date)

        logger.info(
            "[daily_indicator.incremental] 完成: range=%s~%s days=%d succeeded=%d failed=%d persisted=%d",
            start_date, end_date, total, succeeded, failed, total_persisted,
        )
        return {"total": total, "succeeded": succeeded, "failed": failed, "persisted": total_persisted}

    async def _process_trade_date(
        self,
        trade_date: date,
        watermark_map: dict[str, date],
    ) -> int:
        """处理单个交易日：采集→清洗→持久化→更新标的水位。"""
        ts_date = trade_date.strftime("%Y%m%d")

        # 采集全市场当日数据
        df = await _get_collector().fetch_daily_basic(trade_date=ts_date)
        if df is None or df.empty:
            logger.debug("[daily_indicator.incremental] 无数据: %s", trade_date)
            return 0

        # 检查是否达到上限
        if len(df) >= _DAILY_BASIC_ROW_LIMIT:
            logger.warning(
                "[daily_indicator.incremental] 返回 %d 条达到上限 %d: %s",
                len(df), _DAILY_BASIC_ROW_LIMIT, trade_date,
            )

        # 清洗
        df = clean_daily_indicator_data(df)
        if df.empty:
            return 0

        # 按标的水位过滤：单日采集，直接过滤水位 >= 当日的标的
        if watermark_map:
            skip_codes = {code for code, wm in watermark_map.items() if wm >= trade_date}
            if skip_codes:
                df = df[~df["symbol"].isin(skip_codes)]
                if df.empty:
                    return 0

        # 持久化
        count = await persist_daily_indicator_data(df)

        # 更新标的级水位
        if count > 0:
            await self._update_item_watermarks(df, trade_date)

        return count

    @staticmethod
    async def _get_trade_dates(start_date: date, end_date: date) -> list[date]:
        """获取日期范围内的交易日列表。"""
        rows = await TradeCalendar.filter(
            exchange="SSE",
            is_open=True,
            cal_date__gte=start_date,
            cal_date__lte=end_date,
            order_by=TradeCalendar.cal_date.asc(),
        )
        return [row.cal_date for row in rows]

    @staticmethod
    async def _get_watermark_map() -> dict[str, date]:
        """获取标的级水位映射 {code: watermark_date}。"""
        rows = await CollectWatermark.filter(pipeline_name=_ITEM_PIPELINE_NAME, status="active")
        return {row.watermark_code: row.watermark_date for row in rows if row.watermark_date is not None}

    @staticmethod
    async def _update_item_watermarks(df: pd.DataFrame, trade_date: date) -> None:
        """批量更新有新数据的标的的水位日期（使用 bulk_create_or_update）。"""
        codes = df["symbol"].unique().tolist()
        instances = [
            CollectWatermark(
                pipeline_name=_ITEM_PIPELINE_NAME,
                watermark_code=code,
                watermark_date=trade_date,
                record_count=0,
                status="active",
            )
            for code in codes
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
