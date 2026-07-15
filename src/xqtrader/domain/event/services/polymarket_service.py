"""Polymarket 预测市场服务 — 前瞻性事件概率数据源。

架构文档 §14.6 可选扩展：作为 event-monitor 的可选输入。

数据源：Polymarket Gamma API（公开 REST，无需认证）
  - 端点：https://gamma-api.polymarket.com/events
  - 查询参数：limit, closed, order, ascending, tag_id
  - 响应：事件列表，每个事件含 markets 数组（含 outcomePrices/volume/liquidity）

应用场景：地缘政治事件（开战/停火概率）、贸易政策（关税概率）、
选举结果、加密货币价格预期等。

采集失败处理：与 Yahoo Finance 一致，失败返回空列表并记录 WARNING，
不降级、不 fallback、不重试。
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from framework.commons.logger import get_logger
from xqtrader.domain.event.models import PolymarketEvent

logger = get_logger("EVENT.POLYMARKET")

# Polymarket Gamma API
_GAMMA_API_URL = "https://gamma-api.polymarket.com/events"
_POLYMARKET_TIMEOUT = 15.0
_POLYMARKET_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}
_POLYMARKET_SITE = "https://polymarket.com/event/"

# 默认查询参数：仅活跃市场，按成交量降序
_DEFAULT_PARAMS: dict[str, Any] = {
    "closed": "false",
    "order": "volume",
    "ascending": "false",
}


class PolymarketService:
    """Polymarket 预测市场查询服务。"""

    async def get_events(
        self,
        *,
        keyword: str | None = None,
        min_volume: float = 1000.0,
        limit: int = 10,
    ) -> list[PolymarketEvent]:
        """查询 Polymarket 预测市场事件。

        Args:
            keyword: 关键词过滤（如 "bitcoin" / "election"），None 表示不过滤
            min_volume: 最小成交量阈值（USD），过滤低流动性市场
            limit: 返回事件数上限

        Returns:
            PolymarketEvent 列表，按成交量降序；采集失败返回空列表
        """
        raw_events = await self._fetch_events(limit=limit)
        if not raw_events:
            return []

        events = self._parse_events(raw_events, keyword=keyword, min_volume=min_volume)
        logger.info(
            "Polymarket 事件查询完成: keyword=%s min_volume=%s "
            "raw=%d filtered=%d",
            keyword, min_volume, len(raw_events), len(events),
        )
        return events

    async def _fetch_events(self, *, limit: int) -> list[dict[str, Any]]:
        """从 Polymarket Gamma API 拉取事件列表。

        失败返回空列表（不降级、不重试）。
        """
        params = dict(_DEFAULT_PARAMS)
        # Gamma API 的 limit 是单页大小，上限拉取后服务端按 volume 排序返回
        params["limit"] = str(limit * 2)
        try:
            async with httpx.AsyncClient(timeout=_POLYMARKET_TIMEOUT) as client:
                response = await client.get(
                    _GAMMA_API_URL,
                    headers=_POLYMARKET_HEADERS,
                    params=params,
                )
                response.raise_for_status()
                body = response.json()
            if not isinstance(body, list):
                logger.warning(
                    "Polymarket Gamma API 响应格式异常: 期望 list, got %s",
                    type(body).__name__,
                )
                return []
            return body
        except httpx.HTTPError as exc:
            logger.warning("Polymarket Gamma API 采集失败 (HTTP): %s", exc)
            return []
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Polymarket Gamma API 响应解析失败: %s", exc)
            return []

    def _parse_events(
        self,
        raw_events: list[dict[str, Any]],
        *,
        keyword: str | None,
        min_volume: float,
    ) -> list[PolymarketEvent]:
        """解析原始事件列表为 PolymarketEvent。

        Args:
            raw_events: Gamma API 返回的原始事件列表
            keyword: 关键词过滤（不区分大小写，匹配 title/question）
            min_volume: 最小成交量阈值
        """
        keyword_lower = keyword.lower().strip() if keyword else None
        events: list[PolymarketEvent] = []
        for raw in raw_events:
            if not isinstance(raw, dict):
                continue
            parsed = self._parse_single_event(raw)
            if parsed is None:
                continue
            # 关键词过滤：匹配 question
            if keyword_lower and keyword_lower not in parsed.question.lower():
                continue
            # 成交量过滤
            if parsed.volume < min_volume:
                continue
            events.append(parsed)
        return events

    def _parse_single_event(self, raw: dict[str, Any]) -> PolymarketEvent | None:
        """解析单个事件。

        一个 Gamma event 可能含多个 markets（如总统选举多州），
        取 volume 最大的 market 作为代表市场。
        """
        title = str(raw.get("title", "")).strip()
        slug = str(raw.get("slug", "")).strip() or None
        if not title:
            return None

        markets = raw.get("markets")
        if not isinstance(markets, list) or not markets:
            return None

        # 选 volume 最大的 market
        best_market: dict[str, Any] | None = None
        best_volume = -1.0
        for m in markets:
            if not isinstance(m, dict):
                continue
            vol = self._parse_float(m.get("volume"))
            if vol is not None and vol > best_volume:
                best_volume = vol
                best_market = m
        if best_market is None:
            return None

        # outcomePrices: ["0.65", "0.35"] → yes_pct = 0.65
        yes_pct = self._extract_yes_pct(best_market)
        volume = self._parse_float(best_market.get("volume")) or 0.0
        liquidity = self._parse_float(best_market.get("liquidity"))
        end_date = str(best_market.get("endDate") or "").strip() or None
        category = self._extract_category(raw)
        url = f"{_POLYMARKET_SITE}{slug}" if slug else None

        return PolymarketEvent(
            question=title,
            yes_pct=yes_pct,
            volume=volume,
            liquidity=liquidity,
            end_date=end_date,
            url=url,
            category=category,
            slug=slug,
        )

    def _extract_yes_pct(self, market: dict[str, Any]) -> float:
        """从 market.outcomePrices 提取 Yes 概率。

        outcomePrices 格式：["0.65", "0.35"]，第一个为 Yes。
        若缺失，从 bestAsk/bestBid 估算；仍缺失返回 0.0。
        """
        prices = market.get("outcomePrices")
        if isinstance(prices, str):
            # JSON 字符串形式：'["0.65", "0.35"]'
            try:
                prices = json.loads(prices)
            except (json.JSONDecodeError, TypeError):
                prices = None
        if isinstance(prices, list) and prices:
            first = prices[0]
            pct = self._parse_float(first)
            if pct is not None:
                # Polymarket outcomePrices 可能是 0-1 或 0-100
                return pct / 100.0 if pct > 1.0 else pct
        # 兜底：从 bestBid/bestAsk 中点估算
        bid = self._parse_float(market.get("bestBid"))
        ask = self._parse_float(market.get("bestAsk"))
        if bid is not None and ask is not None and 0 <= bid <= ask <= 1:
            return (bid + ask) / 2.0
        return 0.0

    def _extract_category(self, raw: dict[str, Any]) -> str | None:
        """从事件的 tags 提取分类标签（取第一个）。"""
        tags = raw.get("tags")
        if isinstance(tags, list) and tags:
            first = tags[0]
            if isinstance(first, dict):
                tag_name = first.get("label") or first.get("slug")
                if isinstance(tag_name, str) and tag_name.strip():
                    return tag_name.strip()
            elif isinstance(first, str) and first.strip():
                return first.strip()
        return None

    @staticmethod
    def _parse_float(value: Any) -> float | None:
        """安全解析数值字段（容错字符串/None/异常类型）。"""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return None


# 模块级单例
polymarket_service = PolymarketService()
