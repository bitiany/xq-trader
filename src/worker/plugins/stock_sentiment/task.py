"""市场舆情快照采集任务（akshare 微博财经舆情）。

数据源：akshare stock_js_weibo_report（微博财经舆情报告）

特点：
  - 市场级舆情（symbol='' 空串占位），不按标的循环
  - 按日期采集（date_str 参数，YYYYMMDD 格式）
  - 写入 sdc_stock_sentiment 表，sentiment_type='weibo'
  - 复合唯一约束：snapshot_date + sentiment_type + symbol

不使用 Pipeline 引擎（无需并发，单次调用即可）。
不使用 WatermarkAspect（按日期触发，非按标的增量）。
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

import pandas as pd

from framework.commons.logger import get_logger
from framework.scheduler.base_task import BaseTask
from xqtrader.broker.services.akshare_data_collector import AkshareDataCollector
from xqtrader.domain.research.models.stock_sentiment import StockSentiment
from xqtrader.domain.watermark.services.watermark_service import WatermarkService

logger = get_logger(__name__)

_collector: AkshareDataCollector | None = None

# ORM 可更新字段（复合唯一键不更新）
_PERSIST_UPDATE_FIELDS = [
    "heat_score", "sentiment_score", "positive_count", "negative_count",
    "neutral_count", "keywords", "summary", "updated_at",
]


def _get_collector() -> AkshareDataCollector:
    """延迟初始化 AkshareDataCollector 单例。"""
    global _collector  # noqa: PLW0603
    if _collector is None:
        _collector = AkshareDataCollector()
    return _collector


def clean_sentiment_data(
    df: pd.DataFrame,
    snapshot_date: date_type,
    sentiment_type: str,
) -> pd.DataFrame:
    """舆情数据清洗 — 设置 snapshot_date / sentiment_type / symbol 字段。

    akshare stock_js_weibo_report 返回字段（典型）：
      日期 / 关键词 / 热度 / 正面 / 负面 / 中性
    本任务将市场级舆情聚合为单条快照：
      - symbol 设为 ''（市场级，空串占位）
      - snapshot_date 设为入参日期
      - sentiment_type 设为 'weibo'
      - 聚合热度/正负面计数
    """
    if df.empty:
        return df

    # 聚合为单行快照（市场级）
    # akshare 返回的是关键词列表，每行一个关键词；聚合后取总热度、正/负/中性提及数总和
    snapshot: dict[str, Any] = {
        "snapshot_date": snapshot_date,
        "sentiment_type": sentiment_type,
        "symbol": "",
    }

    # 尝试解析热度列
    heat_cols = [c for c in df.columns if "热度" in str(c)]
    if heat_cols:
        snapshot["heat_score"] = float(pd.to_numeric(df[heat_cols[0]], errors="coerce").sum())

    # 尝试解析正/负/中性提及数
    pos_cols = [c for c in df.columns if "正面" in str(c) or "积极" in str(c)]
    neg_cols = [c for c in df.columns if "负面" in str(c) or "消极" in str(c)]
    neu_cols = [c for c in df.columns if "中性" in str(c)]
    if pos_cols:
        snapshot["positive_count"] = int(pd.to_numeric(df[pos_cols[0]], errors="coerce").sum())
    if neg_cols:
        snapshot["negative_count"] = int(pd.to_numeric(df[neg_cols[0]], errors="coerce").sum())
    if neu_cols:
        snapshot["neutral_count"] = int(pd.to_numeric(df[neu_cols[0]], errors="coerce").sum())

    # 关键词列表（取前 20 个热门关键词）
    keyword_cols = [c for c in df.columns if "关键词" in str(c) or "词" in str(c)]
    if keyword_cols:
        keywords_series = df[keyword_cols[0]].dropna()
        keywords = [
            {"word": str(k), "count": 0}
            for k in keywords_series.head(20)
            if str(k) not in {"nan", "None", ""}
        ]
        if keywords:
            snapshot["keywords"] = keywords

    # 摘要：拼接前 5 个关键词
    if "keywords" in snapshot and snapshot["keywords"]:
        words = [kw["word"] for kw in snapshot["keywords"][:5]]
        snapshot["summary"] = "热门关键词: " + " / ".join(words)

    return pd.DataFrame([snapshot])


async def persist_sentiment_data(df: pd.DataFrame) -> int:
    """将舆情快照 upsert 到 StockSentiment 表。"""
    if df.empty:
        return 0

    instances: list[StockSentiment] = []
    for _, row in df.iterrows():
        snapshot_date = row.get("snapshot_date")
        if not isinstance(snapshot_date, date_type):
            continue

        instance = StockSentiment(
            symbol=row.get("symbol", "") or "",
            snapshot_date=snapshot_date,
            sentiment_type=row.get("sentiment_type", "weibo"),
            heat_score=row.get("heat_score"),
            sentiment_score=row.get("sentiment_score"),
            positive_count=row.get("positive_count"),
            negative_count=row.get("negative_count"),
            neutral_count=row.get("neutral_count"),
            keywords=row.get("keywords"),
            summary=row.get("summary"),
        )
        instances.append(instance)

    if not instances:
        return 0

    return await StockSentiment.bulk_create_or_update(
        instances,  # type: ignore[arg-type]
        on_conflict=["snapshot_date", "sentiment_type", "symbol"],
        update_fields=_PERSIST_UPDATE_FIELDS,
        batch_size=50,
    )


def _parse_date_str(date_str: str) -> date_type | None:
    """将 YYYYMMDD 或 YYYY-MM-DD 字符串解析为 date 对象。"""
    if not date_str:
        return None
    try:
        normalized = date_str.replace("-", "")
        if len(normalized) == 8:
            return date_type(int(normalized[:4]), int(normalized[4:6]), int(normalized[6:8]))
    except (ValueError, IndexError):
        return None
    return None


class StockSentimentCollectTask(BaseTask):
    """市场舆情快照采集任务（akshare 微博财经舆情）。

    入参：
      - collect_date: 采集日期（YYYYMMDD，为空时取最近交易日）
      - sentiment_type: 舆情类型标识（默认 weibo）
    """

    task_name = "market.stock_sentiment_collect"
    description = "市场舆情快照采集-akshare微博财经舆情（按日期聚合为单条快照）"

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        collect_date: str | None = kwargs.get("collect_date")
        sentiment_type: str = kwargs.get("sentiment_type", "weibo")

        # 确定采集日期
        if collect_date:
            snapshot_date = _parse_date_str(collect_date)
            date_str_param = collect_date.replace("-", "")
        else:
            service = WatermarkService()
            latest = await service.get_latest_trade_date()
            if latest is None:
                logger.warning("[stock_sentiment.collect] 未找到最近交易日")
                return {"total": 0, "succeeded": 0, "failed": 0}
            snapshot_date = latest
            date_str_param = latest.strftime("%Y%m%d")

        if snapshot_date is None:
            logger.warning("[stock_sentiment.collect] 日期解析失败: %s", collect_date)
            return {"total": 0, "succeeded": 0, "failed": 0}

        logger.info(
            "[stock_sentiment.collect] 开始采集: date=%s type=%s",
            snapshot_date, sentiment_type,
        )

        try:
            df = await _get_collector().fetch_weibo_sentiment(date_str=date_str_param)

            if df is None or df.empty:
                logger.info(
                    "[stock_sentiment.collect] 无数据: date=%s",
                    snapshot_date,
                )
                return {"total": 1, "succeeded": 0, "failed": 0}

            logger.info(
                "[stock_sentiment.collect] 原始数据: date=%s rows=%d cols=%s",
                snapshot_date, len(df), list(df.columns),
            )

            # 清洗 + 聚合
            df = clean_sentiment_data(df, snapshot_date, sentiment_type)

            # 持久化
            count = await persist_sentiment_data(df)

            logger.info(
                "[stock_sentiment.collect] 完成: date=%s persisted=%d",
                snapshot_date, count,
            )
            return {
                "total": 1,
                "succeeded": 1 if count > 0 else 0,
                "failed": 0 if count > 0 else 1,
                "snapshot_date": str(snapshot_date),
                "rows": count,
            }
        except Exception as e:
            logger.error(
                "[stock_sentiment.collect] 采集失败 date=%s: %s",
                snapshot_date, e, exc_info=True,
            )
            return {
                "total": 1,
                "succeeded": 0,
                "failed": 1,
                "error": str(e),
                "snapshot_date": str(snapshot_date),
            }
