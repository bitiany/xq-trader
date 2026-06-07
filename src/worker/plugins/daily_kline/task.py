"""A股日线K线行情采集任务。

数据源：QMT (xtdata)，采集日线K线行情写入 CandlestickDaily 表。
管线流程（每个标的串行执行）：
  WatermarkAspect(前切) → DownloadStage → CleanStage → PersistStage → WatermarkAspect(后切)

数据清洗逻辑（CleanStage）：
  1. 删除 trade_date 为空的行
  2. 数值列（OHLC/Volume/Amount/Change/PreClose/PctChg）强制转 numeric
  3. OHLC 负值置 NaN，用前后值填充（bfill + ffill）
  4. Volume/Amount 缺失填充 0
  5. PreClose 缺失时用前一日 Close 填充（shift(1)），首行用当日 Close 兜底
  6. PctChg 缺失时用 (Close - PreClose) / PreClose * 100 重算
  7. Change 用 Close.diff() 重算，首行置 0
  8. 数值列精度统一为 4 位小数（Volume 除外）
  9. 删除 OHLC 仍有 NaN 的行

水位管理（WatermarkAspect）：
  - 前切：若指定 collect_date 则以该日期为起始；否则查询水位日期作为增量起始时间
  - 后切：持久化成功后更新水位日期为参考日期（当前或前一交易日）
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from framework.commons.logger import get_logger
from framework.commons.utils.data_converter import DataFrameToModelConverter
from framework.pipeline import (
    Pipeline,
    PipelineContext,
    PipelineEngine,
    PipelineError,
    Stage,
    StageResult,
)
from framework.scheduler.base_task import BaseTask
from worker.plugins.aspects import WatermarkAspect
from xqtrader.broker.services.qmt_data_collector import QmtDataCollector
from xqtrader.domain.market.models.candlestick import CandlestickDaily
from xqtrader.domain.security.models import Security

logger = get_logger(__name__)

_collector = QmtDataCollector()


class DailyKlineError(PipelineError):
    """日线K线采集异常基类。"""


class DownloadError(DailyKlineError):
    """下载阶段异常。"""


class PersistError(DailyKlineError):
    """持久化阶段异常。"""


class DownloadStage(Stage):
    """下载阶段 — 调用 QmtDataCollector 获取日线K线行情数据。"""

    @property
    def name(self) -> str:
        return "download"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        stock_code: str = item
        start_date = ctx.get("start_date", "")
        end_date = ctx.get("end_date", "")

        if ctx.get("is_up_to_date"):
            return StageResult.ok(data={"stock_code": stock_code, "rows": 0, "skipped": True})

        if not start_date:
            return StageResult.fail(f"缺少 start_date，跳过 {stock_code}")

        try:
            # end_date 为空时传远期日期，避免 QmtDataCollector 判定区间倒置
            effective_end_date = end_date if end_date else "20991231"
            result = await _collector.fetch_kline_daily(
                stock_list=[stock_code],
                start_time=start_date,
                end_time=effective_end_date,
            )
            df = result.get(stock_code)
            if df is None or df.empty:
                logger.debug("无数据: %s range=%s~%s", stock_code, start_date, end_date)
                ctx.set("download_data", None)
                ctx.set("row_count", 0)
                ctx.set("skip_persist", True)
            else:
                ctx.set("download_data", df)
                ctx.set("row_count", len(df))
                ctx.set("skip_persist", False)
                ctx.set("data_source", "qmt")

            return StageResult.ok(data={"stock_code": stock_code, "rows": ctx.get("row_count", 0)})
        except Exception as e:
            raise DownloadError(f"下载失败 {stock_code}: {e}") from e


class CleanStage(Stage):
    """清洗阶段 — 对K线数据进行质量校验和修复。"""

    _OHLC_COLS = ["open", "close", "high", "low"]
    _NUMERIC_COLS = ["open", "close", "high", "low", "volume", "amount", "change", "pre_close", "pct_chg"]

    @property
    def name(self) -> str:
        return "clean"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        stock_code: str = item

        if ctx.get("skip_persist"):
            return StageResult.ok(data={"stock_code": stock_code, "cleaned": 0})

        df: pd.DataFrame | None = ctx.get("download_data")
        if df is None or df.empty:
            return StageResult.ok(data={"stock_code": stock_code, "cleaned": 0})

        initial_len = len(df)

        # 1. 删除 trade_date 为空
        df = df.dropna(subset=["trade_date"])
        if df.empty:
            ctx.set("download_data", df)
            ctx.set("row_count", 0)
            return StageResult.ok(data={"stock_code": stock_code, "cleaned": 0})

        # 2. 数值列强制转 numeric
        for col in self._NUMERIC_COLS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 3. OHLC 负值置 NaN，用前后值填充
        ohlc_cols = [c for c in self._OHLC_COLS if c in df.columns]
        if ohlc_cols:
            neg_count = (df[ohlc_cols] < 0).any(axis=1).sum()
            nan_count = df[ohlc_cols].isna().all(axis=1).sum()

            for col in ohlc_cols:
                df.loc[df[col] < 0, col] = np.nan

            for col in ohlc_cols:
                df[col] = df[col].bfill()
                df[col] = df[col].ffill()

            if neg_count > 0 or nan_count > 0:
                logger.debug(
                    "清洗: %s masked %d negative / %d all-NaN OHLC rows",
                    stock_code, neg_count, nan_count,
                )

        # 4. volume/amount 填充 0
        if "volume" in df.columns:
            df["volume"] = df["volume"].fillna(0).astype(int)

        if "amount" in df.columns:
            df["amount"] = df["amount"].fillna(0)

        # 5. pre_close 缺失时用前一日 Close 填充（PreClose = 前日收盘价）
        if "pre_close" in df.columns and "close" in df.columns:
            mask = df["pre_close"].isna()
            if mask.any():
                # 用前一日 Close 填充（shift(1)）
                prev_close = df["close"].shift(1)
                df.loc[mask, "pre_close"] = prev_close[mask]
                # 首行无前日数据，用当日 Close 兜底
                if df["pre_close"].isna().iloc[0]:
                    df.loc[df.index[0], "pre_close"] = df.iloc[0]["close"]
                # 仍有缺失则 ffill + bfill
                df["pre_close"] = df["pre_close"].ffill()
                df["pre_close"] = df["pre_close"].bfill()

        # 6. pct_chg 缺失时重算
        if "pct_chg" in df.columns and "close" in df.columns and "pre_close" in df.columns:
            mask = df["pct_chg"].isna() & df["pre_close"].notna() & (df["pre_close"] != 0)
            df.loc[mask, "pct_chg"] = (
                (df.loc[mask, "close"] - df.loc[mask, "pre_close"])
                / df.loc[mask, "pre_close"] * 100
            ).round(4)

        # 7. change 缺失时重算
        if "change" in df.columns and "close" in df.columns:
            df["change"] = df["close"].diff().round(4)
            df.loc[df.index[0], "change"] = 0.0

        # 8. 数值列精度
        for col in self._NUMERIC_COLS:
            if col in df.columns and col != "volume":
                df[col] = df[col].round(4)

        # 9. 删除 OHLC 仍有 NaN 的行
        if ohlc_cols:
            remaining_nan = df[ohlc_cols].isna().any(axis=1).sum()
            if remaining_nan > 0:
                df = df.dropna(subset=ohlc_cols)
                logger.warning("清洗: %s dropped %d rows with remaining NaN", stock_code, remaining_nan)

        df = df.reset_index(drop=True)
        ctx.set("download_data", df)
        ctx.set("row_count", len(df))

        cleaned = initial_len - len(df)
        if cleaned > 0:
            logger.debug("清洗: %s removed %d invalid rows", stock_code, cleaned)

        return StageResult.ok(data={"stock_code": stock_code, "cleaned": len(df)})


class PersistStage(Stage):
    """持久化阶段 — 将K线数据写入 CandlestickDaily 表。"""

    _COLUMN_MAPPING: dict[str, str] = {}

    _CUSTOM_TRANSFORMS = {
        "trade_date": lambda v: date.fromisoformat(str(v)) if v and str(v) != "nan" else None,
    }

    _UPDATE_FIELDS = [
        "open", "close", "high", "low", "volume", "amount",
        "change", "pre_close", "pct_chg", "data_source",
    ]

    @property
    def name(self) -> str:
        return "persist"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        stock_code: str = item

        if ctx.get("skip_persist"):
            return StageResult.ok(data={"stock_code": stock_code, "persisted": 0})

        df: pd.DataFrame | None = ctx.get("download_data")
        if df is None or df.empty:
            return StageResult.ok(data={"stock_code": stock_code, "persisted": 0})

        try:
            df["symbol"] = stock_code
            df["data_source"] = ctx.get("data_source", "qmt")

            instances = DataFrameToModelConverter.convert(
                df=df,
                model_class=CandlestickDaily,
                column_mapping=self._COLUMN_MAPPING,
                custom_transforms=self._CUSTOM_TRANSFORMS,
            )

            if not instances:
                return StageResult.ok(data={"stock_code": stock_code, "persisted": 0})

            count = await CandlestickDaily.bulk_create_or_update(
                instances,
                on_conflict=["symbol", "trade_date"],
                update_fields=self._UPDATE_FIELDS,
                batch_size=100,
            )

            ctx.set("persisted_count", count)
            logger.debug("持久化完成: %s rows=%d", stock_code, count)
            return StageResult.ok(data={"stock_code": stock_code, "persisted": count})
        except Exception as e:
            raise PersistError(f"持久化失败 {stock_code}: {e}") from e



class DailyKlineCollectTask(BaseTask):
    """A股日线K线行情采集任务。

    入参：
      - pipeline_name: 管线名称（默认 daily_kline）
      - concurrency: 并发数（默认 5）
      - stock_codes: 股票代码列表（为空时采集全市场）
      - max_count: 最大标的数量（用于测试，0 表示不限）
      - collect_date: 采集起始日期（格式 YYYY-MM-DD，为空时按水位日期增量采集）
    """

    task_name = "market.daily_kline_collect"
    description = "A股日线K线行情采集（管道引擎并发）"
    time_limit = 1800
    soft_time_limit = 1770

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        pipeline_name = kwargs.get("pipeline_name", "daily_kline")
        concurrency = kwargs.get("concurrency", 5)
        stock_codes: list[str] | None = kwargs.get("stock_codes")
        max_count: int = kwargs.get("max_count", 0)
        collect_date: str | None = kwargs.get("collect_date")

        # 获取标的列表
        if not stock_codes:
            stock_codes = await self._get_all_stock_codes()
            if not stock_codes:
                logger.warning("未找到任何标的代码")
                return {"total": 0, "succeeded": 0, "failed": 0}

        # 限制标的数量（用于测试）
        if max_count > 0 and len(stock_codes) > max_count:
            stock_codes = stock_codes[:max_count]
            logger.debug("限制标的数量: max_count=%d", max_count)

        # 构建全局上下文
        global_ctx: dict[str, Any] = {}
        if collect_date:
            global_ctx["collect_date"] = collect_date

        logger.info(
            "开始采集: pipeline=%s concurrency=%d stocks=%d collect_date=%s",
            pipeline_name, concurrency, len(stock_codes), collect_date or "按水位",
        )

        # 组装管线: download → clean → persist
        pipeline = Pipeline(
            name=pipeline_name,
            stages=[DownloadStage(), CleanStage(), PersistStage()],
            aspects=[WatermarkAspect(pipeline_name=pipeline_name)],
        )

        # 执行管道引擎
        engine = PipelineEngine(
            pipelines=[pipeline],
            concurrency=concurrency,
            global_context=global_ctx,
        )
        result = await engine.execute(stock_codes)

        return result.to_dict()

    @staticmethod
    async def _get_all_stock_codes() -> list[str]:
        """获取全市场 A 股标的代码。"""
        rows = await Security.filter(
            list_status="L",
            order_by=Security.symbol.asc(),
        )
        codes = [row.symbol for row in rows]
        logger.debug("全市场标的数: %d", len(codes))
        return codes
