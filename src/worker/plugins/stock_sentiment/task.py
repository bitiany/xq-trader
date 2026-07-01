"""市场舆情快照采集任务（akshare 微博财经舆情）。

数据源：akshare stock_js_weibo_report（微博财经舆情报告）

特点：
  - 市场级舆情（symbol='' 空串占位），不按标的循环
  - stock_js_weibo_report 不支持按日期查询，只返回指定时间段的最新数据
  - snapshot_date 取采集当天的日期
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

logger = get_logger(__name__)

_collector: AkshareDataCollector | None = None

# ORM 可更新字段（复合唯一键不更新）
_PERSIST_UPDATE_FIELDS = [
    "heat_score", "sentiment_score", "positive_count", "negative_count",
    "neutral_count", "keywords", "summary", "updated_at",
]

# 合法的时间周期值
_VALID_TIME_PERIODS = {"CNHOUR2", "CNHOUR6", "CNHOUR12", "CNHOUR24", "CNDAY7", "CNDAY30"}


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
    """舆情数据清洗 — 将 akshare 原始数据聚合为单条快照。

    akshare stock_js_weibo_report 实际返回字段：
      name: 股票/关键词名称（如"比亚迪"、"贵州茅台"）
      rate: 情感评分（float，正值=正面/负值=负面，范围约 -5~+5）

    聚合逻辑：
      - symbol 设为 ''（市场级，空串占位）
      - snapshot_date 设为入参日期
      - sentiment_type 设为 'weibo'
      - sentiment_score = rate 平均值（整体情感倾向）
      - positive_count = rate > 0 的数量
      - negative_count = rate < 0 的数量
      - neutral_count = rate == 0 的数量
      - heat_score = |rate| 平均值（整体热度）
      - keywords = 前 20 个标的（name + rate）
    """
    if df.empty:
        return df

    snapshot: dict[str, Any] = {
        "snapshot_date": snapshot_date,
        "sentiment_type": sentiment_type,
        "symbol": "",
    }

    # 解析 name 和 rate 列
    name_col = "name" if "name" in df.columns else df.columns[0]
    rate_col = "rate" if "rate" in df.columns else (df.columns[1] if len(df.columns) > 1 else None)

    if rate_col is not None:
        rates = pd.to_numeric(df[rate_col], errors="coerce").dropna()
        if not rates.empty:
            snapshot["sentiment_score"] = float(rates.mean())
            snapshot["positive_count"] = int((rates > 0).sum())
            snapshot["negative_count"] = int((rates < 0).sum())
            snapshot["neutral_count"] = int((rates == 0).sum())
            snapshot["heat_score"] = float(rates.abs().mean())

    # 关键词列表（取前 20 个，含 name 和 rate）
    names = df[name_col].dropna()
    rate_series = (
        pd.to_numeric(df[rate_col], errors="coerce")
        if rate_col is not None else None
    )
    keywords: list[dict[str, Any]] = []
    for idx, n in names.head(20).items():
        name_str = str(n)
        if name_str in {"nan", "None", ""}:
            continue
        rate_value = 0.0
        if rate_series is not None:
            try:
                rate_raw = rate_series.get(idx, 0.0)
                if not pd.isna(rate_raw):
                    rate_value = float(rate_raw)
            except (ValueError, TypeError):
                rate_value = 0.0
        keywords.append({"word": name_str, "rate": rate_value})

    if keywords:
        snapshot["keywords"] = keywords
        words = [str(kw["word"]) for kw in keywords[:5]]
        snapshot["summary"] = "热门标的: " + " / ".join(words)

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
      - collect_date: 快照日期（YYYYMMDD，为空时取当天）
      - sentiment_type: 舆情类型标识（默认 weibo）
      - time_period: 时间周期（默认 CNDAY7，可选 CNHOUR2/CNHOUR6/CNHOUR12/CNHOUR24/CNDAY7/CNDAY30）
    """

    task_name = "market.stock_sentiment_collect"
    description = "市场舆情快照采集-akshare微博财经舆情（按日期聚合为单条快照）"

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        collect_date: str | None = kwargs.get("collect_date")
        sentiment_type: str = kwargs.get("sentiment_type", "weibo")
        time_period: str = kwargs.get("time_period", "CNDAY7")

        # 校验 time_period
        if time_period not in _VALID_TIME_PERIODS:
            logger.warning(
                "[stock_sentiment.collect] 无效的 time_period=%s，使用默认 CNDAY7",
                time_period,
            )
            time_period = "CNDAY7"

        # 确定快照日期（stock_js_weibo_report 不支持历史查询，snapshot_date 取当天）
        if collect_date:
            snapshot_date = _parse_date_str(collect_date)
        else:
            snapshot_date = date_type.today()

        if snapshot_date is None:
            logger.warning("[stock_sentiment.collect] 日期解析失败: %s", collect_date)
            return {"total": 0, "succeeded": 0, "failed": 0}

        logger.info(
            "[stock_sentiment.collect] 开始采集: date=%s type=%s time_period=%s",
            snapshot_date, sentiment_type, time_period,
        )

        try:
            df = await _get_collector().fetch_weibo_sentiment(time_period=time_period)

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
