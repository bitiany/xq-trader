"""个股新闻与公告采集任务（akshare 数据源）。

数据源：
  - 新闻：akshare stock_news_em（东方财富新闻频道）
  - 公告：akshare stock_individual_notice_report（巨潮/东财公告）

管线流程（每个标的串行执行）：
  WatermarkAspect(前切) → DownloadStage → PersistStage → WatermarkAspect(后切)

注意：
  - 新闻接口不支持日期范围参数，每次返回近期约 100 条，依赖 news_url 唯一约束去重
  - 公告接口支持 begin_date/end_date（YYYYMMDD），按水位增量采集
  - 合并写入 sdc_stock_news 表，用 news_type 字段区分（news/announcement）
  - 水位管理：水位最新时跳过公告采集，但新闻始终采集（新闻无日期参数）
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any

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
from worker.plugins.utils import parse_list_param
from xqtrader.broker.services.akshare_data_collector import (
    AkshareDataCollector,
    normalize_news_keywords,
)
from xqtrader.domain.research.models.stock_news import StockNews
from xqtrader.domain.security.models import Security

logger = get_logger(__name__)

_collector: AkshareDataCollector | None = None

_DATA_TYPE = "stock_news"

# ORM 可更新字段（news_url 为唯一键，不更新）
_PERSIST_UPDATE_FIELDS = [
    "symbol", "news_type", "title", "content", "source",
    "publish_time", "keywords", "updated_at",
]


def _get_collector() -> AkshareDataCollector:
    """延迟初始化 AkshareDataCollector 单例。"""
    global _collector  # noqa: PLW0603
    if _collector is None:
        _collector = AkshareDataCollector()
    return _collector


def clean_stock_news_data(df: pd.DataFrame) -> pd.DataFrame:
    """新闻/公告数据清洗 — 过滤无效行。"""
    if df.empty:
        return df

    # 过滤缺少 news_url 或 title 的行（news_url 是唯一键）
    df = df.dropna(subset=["news_url", "title"])
    if df.empty:
        return df

    # publish_time 转换为 datetime
    if "publish_time" in df.columns:
        df["publish_time"] = pd.to_datetime(df["publish_time"], errors="coerce")

    return df.reset_index(drop=True)


async def persist_stock_news_data(df: pd.DataFrame) -> tuple[int, date_type | None]:
    """将新闻/公告数据 upsert 到 StockNews 表。

    Returns:
        (持久化行数, 最大 publish_time 的日期部分)
    """
    custom_transforms = {
        "publish_time": lambda v: v if isinstance(v, datetime) and not pd.isna(v) else None,
        # keywords 为 JSONB 数组，DataFrameToModelConverter 兜底转 str，
        # 需通过 normalize_news_keywords 显式保留 list 类型
        "keywords": lambda v: normalize_news_keywords(v),
    }
    instances = DataFrameToModelConverter.convert(
        df=df,
        model_class=StockNews,
        custom_transforms=custom_transforms,
    )
    if not instances:
        return 0, None

    count = await StockNews.bulk_create_or_update(
        instances,  # type: ignore[arg-type]
        on_conflict=["news_url"],
        update_fields=_PERSIST_UPDATE_FIELDS,
        batch_size=100,
    )

    # 计算最大 publish_time 日期，用于水位更新
    max_date: date_type | None = None
    if "publish_time" in df.columns:
        valid_times = [
            t for t in df["publish_time"].dropna()
            if isinstance(t, datetime) or hasattr(t, "date")
        ]
        if valid_times:
            max_time = max(valid_times)
            max_date = max_time.date() if hasattr(max_time, "date") else None

    return count, max_date


class StockNewsError(PipelineError):
    """新闻采集异常基类。"""


class DownloadError(StockNewsError):
    """下载阶段异常。"""


class PersistError(StockNewsError):
    """持久化阶段异常。"""


class DownloadStage(Stage):
    """下载阶段 — 拉取新闻 + 公告并合并。

    水位策略：
      - 新闻接口不支持日期范围，始终拉取近期数据（依赖 news_url 去重）
      - 公告接口按水位增量采集（start_date ~ end_date）
      - 水位最新时（is_up_to_date=True）跳过公告，但仍拉取新闻
    """

    @property
    def name(self) -> str:
        return "download"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        stock_code: str = item
        fetch_news: bool = ctx.get("fetch_news", True)
        fetch_announcements: bool = ctx.get("fetch_announcements", True)
        # WatermarkAspect 设置的 start_date/end_date（YYYYMMDD）
        ann_begin_date: str = ctx.get("start_date", "")
        ann_end_date: str = ctx.get("end_date", "")
        is_up_to_date: bool = ctx.get("is_up_to_date", False)

        # 水位最新时跳过公告采集
        skip_announcements = (not fetch_announcements) or is_up_to_date

        try:
            frames: list[pd.DataFrame] = []
            news_count = 0
            ann_count = 0

            # 1. 拉取新闻（不支持日期范围，返回近期全部）
            if fetch_news:
                try:
                    news_df = await _get_collector().fetch_stock_news(symbol=stock_code)
                    if not news_df.empty:
                        frames.append(news_df)
                        news_count = len(news_df)
                except Exception as e:
                    logger.warning(
                        "[stock_news.collect] 新闻拉取失败 %s: %s",
                        stock_code, e, exc_info=True,
                    )

            # 2. 拉取公告（按水位日期范围增量）
            if not skip_announcements:
                try:
                    ann_df = await _get_collector().fetch_stock_announcements(
                        symbol=stock_code,
                        begin_date=ann_begin_date,
                        end_date=ann_end_date,
                    )
                    if not ann_df.empty:
                        frames.append(ann_df)
                        ann_count = len(ann_df)
                except Exception as e:
                    logger.warning(
                        "[stock_news.collect] 公告拉取失败 %s range=%s~%s: %s",
                        stock_code, ann_begin_date, ann_end_date, e, exc_info=True,
                    )

            if not frames:
                logger.debug(
                    "[stock_news.collect] 无数据: %s news=%d ann=%d skip_ann=%s",
                    stock_code, news_count, ann_count, skip_announcements,
                )
                ctx.set("download_data", None)
                ctx.set("row_count", 0)
                ctx.set("skip_persist", True)
            else:
                df = pd.concat(frames, ignore_index=True)
                df = clean_stock_news_data(df)
                ctx.set("download_data", df)
                ctx.set("row_count", len(df))
                ctx.set("skip_persist", df.empty)

            return StageResult.ok(
                data={
                    "stock_code": stock_code,
                    "rows": ctx.get("row_count", 0),
                    "news": news_count,
                    "ann": ann_count,
                    "skip_announcements": skip_announcements,
                },
            )
        except Exception as e:
            raise DownloadError(f"下载失败 {stock_code}: {e}") from e


class PersistStage(Stage):
    """持久化阶段 — 写入 StockNews 表并设置水位更新所需的 max_ann_date。"""

    @property
    def name(self) -> str:
        return "persist"

    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        stock_code: str = item

        if ctx.get("skip_persist"):
            return StageResult.ok(data={"stock_code": stock_code, "persisted": 0})

        df = ctx.get("download_data")
        if df is None or df.empty:
            return StageResult.ok(data={"stock_code": stock_code, "persisted": 0})

        try:
            count, max_date = await persist_stock_news_data(df)

            ctx.set("persisted_count", count)
            # WatermarkAspect 后切读取 max_ann_date 更新水位
            if count > 0 and max_date is not None:
                ctx.set("max_ann_date", max_date)

            logger.debug(
                "[stock_news.collect] 持久化完成: %s rows=%d max_date=%s",
                stock_code, count, max_date,
            )
            return StageResult.ok(data={"stock_code": stock_code, "persisted": count})
        except Exception as e:
            raise PersistError(f"持久化失败 {stock_code}: {e}") from e


class StockNewsCollectTask(BaseTask):
    """个股新闻与公告采集任务（akshare 数据源）。

    入参：
      - concurrency: 并发数（默认 3）
      - stock_codes: 股票代码列表（为空时采集全市场）
      - max_count: 最大标的数量（用于测试，0 表示不限）
      - collect_date: 指定采集起始日期（YYYYMMDD 或 YYYY-MM-DD，为空时按水位增量）
      - fetch_news: 是否采集新闻（默认 true）
      - fetch_announcements: 是否采集公告（默认 true）
    """

    task_name = "market.stock_news_collect"
    description = "个股新闻与公告采集-akshare（新闻+公告合并，news_type 区分，公告按水位增量）"

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        concurrency = kwargs.get("concurrency", 3)
        stock_codes: list[str] | None = parse_list_param(kwargs.get("stock_codes"))
        max_count: int = kwargs.get("max_count", 0)
        collect_date: str | None = kwargs.get("collect_date")
        fetch_news: bool = kwargs.get("fetch_news", True)
        fetch_announcements: bool = kwargs.get("fetch_announcements", True)

        # 获取标的列表
        if not stock_codes:
            stock_codes = await self._get_all_stock_codes()
            if not stock_codes:
                logger.warning("[stock_news.collect] 未找到任何标的代码")
                return {"total": 0, "succeeded": 0, "failed": 0}

        # 限制标的数量（用于测试）
        if max_count > 0 and len(stock_codes) > max_count:
            stock_codes = stock_codes[:max_count]
            logger.debug("[stock_news.collect] 限制标的数量: max_count=%d", max_count)

        global_ctx: dict[str, Any] = {
            "fetch_news": fetch_news,
            "fetch_announcements": fetch_announcements,
        }
        if collect_date:
            global_ctx["collect_date"] = collect_date

        logger.info(
            "[stock_news.collect] 开始采集: concurrency=%d stocks=%d news=%s ann=%s collect_date=%s",
            concurrency, len(stock_codes), fetch_news, fetch_announcements,
            collect_date or "按水位",
        )

        # 组装管线: download → persist，公告通过 WatermarkAspect 增量
        pipeline = Pipeline(
            name=_DATA_TYPE,
            stages=[DownloadStage(), PersistStage()],
            aspects=[WatermarkAspect(data_type=_DATA_TYPE)],
        )

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
        logger.debug("[stock_news.collect] 全市场标的数: %d", len(codes))
        return codes
