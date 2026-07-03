"""舆情快照查询服务 — 基于已采集的 StockSentiment 表提供只读查询。"""

from __future__ import annotations

from datetime import date
from typing import Any

from xqtrader.domain.research.models.stock_sentiment import StockSentiment


class SentimentService:
    """市场舆情快照服务。"""

    async def get_market_sentiment(self, days: int = 7) -> dict[str, Any]:
        """获取最近 N 天的市场级舆情快照。

        Args:
            days: 返回天数（默认 7）
        """
        rows = await StockSentiment.filter(
            symbol="",
            order_by=StockSentiment.snapshot_date.desc(),
            limit=days,
        )
        return {"items": [self._snapshot(r) for r in rows]}

    async def get_stock_sentiment(
        self, symbol: str, days: int = 7,
    ) -> dict[str, Any]:
        """获取个股最近 N 天的舆情快照。

        Args:
            symbol: 标的代码，如 002049.SZ
            days: 返回天数（默认 7）
        """
        rows = await StockSentiment.filter(
            symbol=symbol,
            order_by=StockSentiment.snapshot_date.desc(),
            limit=days,
        )
        return {"symbol": symbol, "items": [self._snapshot(r) for r in rows]}

    @staticmethod
    def _snapshot(r: StockSentiment) -> dict[str, Any]:
        return {
            "snapshot_date": r.snapshot_date.isoformat() if isinstance(r.snapshot_date, date) else r.snapshot_date,
            "sentiment_type": r.sentiment_type,
            "heat_score": r.heat_score,
            "sentiment_score": r.sentiment_score,
            "positive_count": r.positive_count,
            "negative_count": r.negative_count,
            "neutral_count": r.neutral_count,
            "keywords": r.keywords or [],
            "summary": r.summary,
        }
