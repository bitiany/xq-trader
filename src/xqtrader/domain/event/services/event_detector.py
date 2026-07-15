"""事件检测器 — 两层检测架构（关键词快速 + LLM 精细识别）。

架构文档 §11.3.1 第一层：事件识别与信号映射。

两层检测策略：
  - Layer 1（关键词，毫秒级）：扫描 StockNews 标题/正文，命中关键词即判定事件类型
  - Layer 2（LLM，秒级）：对 Layer 1 未命中的新闻做二次语义识别

数据源：sdc_stock_news 表（已采集的新闻/公告，区分 news/announcement）
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

from framework.commons.exceptions import DataCollectionError
from framework.commons.logger import get_logger
from xqtrader.domain.event.models import DetectedEvent
from xqtrader.domain.event.services.llm_client import LLMClient
from xqtrader.domain.research.models.stock_news import StockNews

logger = get_logger("EVENT.DETECTOR")

_KEYWORDS_DIR = Path(__file__).resolve().parent.parent / "keywords"
_EVENT_KEYWORDS_FILE = _KEYWORDS_DIR / "event_keywords.yaml"
_EVENT_SIGNAL_MAPPING_FILE = _KEYWORDS_DIR / "event_signal_mapping.yaml"

# Layer 2 LLM 单次批处理上限（避免单次 prompt 过长）
_LLM_BATCH_SIZE = 8
# Layer 2 LLM 超时（秒）
_LLM_TIMEOUT = 90.0

_LLM_SYSTEM_PROMPT = (
    "你是 A 股事件检测助手。判断输入的新闻列表中是否包含「利好/利空/政策」三类事件。"
    "若包含，返回 JSON：{\"events\":[{\"event_category\":\"利好/利空/政策\","
    "\"event_type\":\"资产重组/回购增持/业绩预增/股东减持/业绩预减/违规处罚/退市风险/"
    "货币宽松/产业政策/监管收紧\",\"confidence\":0.0-1.0,\"reason\":\"简要原因\"}]}。"
    "若全部新闻均无明显事件，返回 {\"events\":[]}。"
    "事件类型必须严格使用上述枚举值。event_category 必须与 event_type 对应："
    "利好=资产重组/回购增持/业绩预增；利空=股东减持/业绩预减/违规处罚/退市风险；"
    "政策=货币宽松/产业政策/监管收紧。"
)


class EventDetector:
    """事件检测器 — 两层检测（关键词 + LLM）。"""

    def __init__(self) -> None:
        self._keywords: dict[str, dict[str, list[str]]] = self._load_keywords()
        self._signal_mapping: dict[str, dict[str, Any]] = self._load_signal_mapping()
        self._llm = LLMClient()

    def _load_keywords(self) -> dict[str, dict[str, list[str]]]:
        """加载事件关键词库 YAML。"""
        with _EVENT_KEYWORDS_FILE.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise DataCollectionError(f"事件关键词库格式错误: {_EVENT_KEYWORDS_FILE}")
        logger.info(
            "事件关键词库已加载: categories=%s",
            {cat: len(types) for cat, types in data.items()},
        )
        return data

    def _load_signal_mapping(self) -> dict[str, dict[str, Any]]:
        """加载事件→信号映射表 YAML。"""
        with _EVENT_SIGNAL_MAPPING_FILE.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise DataCollectionError(f"事件→信号映射表格式错误: {_EVENT_SIGNAL_MAPPING_FILE}")
        logger.info("事件→信号映射表已加载: types=%s", list(data.keys()))
        return data

    def get_signal_mapping(self, event_type: str) -> dict[str, Any] | None:
        """查询事件类型对应的信号映射（供 API 层使用）。"""
        return self._signal_mapping.get(event_type)

    async def detect_events(
        self,
        symbols: list[str] | None,
        event_types: list[str] | None,
        days: int = 7,
        as_of: date | None = None,
        skip_llm: bool = False,
    ) -> list[DetectedEvent]:
        """批量检测事件 — 两层检测。

        Args:
            symbols: 标的列表（None 表示全部）
            event_types: 事件类型过滤（None 表示全部，如 ["资产重组", "股东减持"]）
            days: 回溯天数
            as_of: 基准日期（None 表示今天）
            skip_llm: 是否跳过 Layer 2 LLM 识别（用于快速扫描或 LLM 不可用时）

        Returns:
            检测到的事件列表
        """
        ref_date = as_of or date.today()
        start_date = ref_date - timedelta(days=days)

        news_list = await self._load_news(symbols, start_date, ref_date)
        if not news_list:
            logger.info(
                "事件检测: 无新闻数据 symbols=%s start=%s end=%s",
                symbols, start_date, ref_date,
            )
            return []

        logger.info(
            "事件检测开始: news_count=%d symbols=%s days=%d skip_llm=%s",
            len(news_list), symbols, days, skip_llm,
        )

        layer1_events = self._detect_by_keywords(news_list)
        matched_news_ids = {e.raw_content for e in layer1_events if e.raw_content}
        unmatched_news = [n for n in news_list if n.news_url not in matched_news_ids]

        layer2_events: list[DetectedEvent] = []
        if skip_llm:
            logger.info(
                "skip_llm=True，跳过 Layer 2 LLM 识别: unmatched_news=%d",
                len(unmatched_news),
            )
        elif unmatched_news and self._llm.is_enabled():
            layer2_events = await self._detect_by_llm(unmatched_news)
        elif unmatched_news and not self._llm.is_enabled():
            logger.warning(
                "LLM 未配置，跳过 Layer 2 精细识别: unmatched_news=%d",
                len(unmatched_news),
            )

        all_events = layer1_events + layer2_events
        if event_types:
            all_events = [e for e in all_events if e.event_type in event_types]

        _min_aware = datetime.min.replace(tzinfo=timezone.utc)
        all_events.sort(key=lambda e: e.news_time or _min_aware, reverse=True)
        logger.info(
            "事件检测完成: total=%d layer1=%d layer2=%d",
            len(all_events), len(layer1_events), len(layer2_events),
        )
        return all_events

    async def _load_news(
        self,
        symbols: list[str] | None,
        start_date: date,
        end_date: date,
    ) -> list[StockNews]:
        """从 sdc_stock_news 表加载新闻/公告。"""
        filters: dict[str, Any] = {
            "publish_time__gte": datetime.combine(start_date, datetime.min.time()),
            "publish_time__lte": datetime.combine(end_date, datetime.max.time()),
            "limit": None,
            "order_by": StockNews.publish_time.desc(),
        }
        if symbols:
            filters["symbol__in"] = symbols
        return await StockNews.filter(**filters)

    def _detect_by_keywords(self, news_list: list[StockNews]) -> list[DetectedEvent]:
        """Layer 1：关键词快速检测（毫秒级）。"""
        events: list[DetectedEvent] = []
        for news in news_list:
            text = f"{news.title} {news.content or ''}"
            for category, types in self._keywords.items():
                for event_type, keywords in types.items():
                    matched = [kw for kw in keywords if kw in text]
                    if matched:
                        events.append(DetectedEvent(
                            event_category=category,
                            event_type=event_type,
                            symbol=news.symbol,
                            title=news.title,
                            news_time=news.publish_time,
                            source=news.source,
                            matched_keywords=matched,
                            detection_layer="keyword",
                            confidence=1.0,
                            raw_content=news.news_url,
                        ))
                        break
        return events

    async def _detect_by_llm(self, news_list: list[StockNews]) -> list[DetectedEvent]:
        """Layer 2：LLM 精细识别（秒级）— 批处理未命中新闻。"""
        events: list[DetectedEvent] = []
        batches = [
            news_list[i:i + _LLM_BATCH_SIZE]
            for i in range(0, len(news_list), _LLM_BATCH_SIZE)
        ]
        results = await asyncio.gather(*[
            self._detect_batch_by_llm(batch) for batch in batches
        ], return_exceptions=True)
        for batch_news, result in zip(batches, results):
            if isinstance(result, Exception):
                logger.error(
                    "LLM 批次识别失败 batch_size=%d: %s",
                    len(batch_news), result, exc_info=True,
                )
                continue
            events.extend(cast("list[DetectedEvent]", result))
        return events

    async def _detect_batch_by_llm(self, batch: list[StockNews]) -> list[DetectedEvent]:
        """单批 LLM 识别。"""
        news_payload = [
            {
                "index": idx,
                "symbol": n.symbol,
                "title": n.title,
                "content": (n.content or "")[:500],
                "news_url": n.news_url,
                "publish_time": n.publish_time.isoformat() if n.publish_time else None,
                "source": n.source,
            }
            for idx, n in enumerate(batch)
        ]
        user_content = (
            f"请分析以下 {len(batch)} 条新闻，识别其中包含的事件：\n"
            f"{yaml.safe_dump(news_payload, allow_unicode=True, default_flow_style=False)}"
        )
        parsed = await self._llm.chat_json(
            system_prompt=_LLM_SYSTEM_PROMPT,
            user_content=user_content,
            timeout=_LLM_TIMEOUT,
        )
        events_raw = parsed.get("events", [])
        if not isinstance(events_raw, list):
            return []
        result: list[DetectedEvent] = []
        for ev in events_raw:
            if not isinstance(ev, dict):
                continue
            event_type = str(ev.get("event_type", "")).strip()
            event_category = str(ev.get("event_category", "")).strip()
            if not event_type or not event_category:
                continue
            if event_type not in self._signal_mapping:
                logger.warning("LLM 返回未知事件类型: %s，跳过", event_type)
                continue
            confidence = float(ev.get("confidence", 0.8))
            idx = int(ev.get("index", -1))
            news = batch[idx] if 0 <= idx < len(batch) else None
            result.append(DetectedEvent(
                event_category=event_category,
                event_type=event_type,
                symbol=news.symbol if news else None,
                title=news.title if news else ev.get("reason", ""),
                news_time=news.publish_time if news else None,
                source=news.source if news else None,
                matched_keywords=[],
                detection_layer="llm",
                confidence=confidence,
                raw_content=news.news_url if news else None,
            ))
        return result
