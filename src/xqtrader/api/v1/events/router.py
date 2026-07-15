"""事件驱动 API — 事件检测、宏观恐慌指数、论点卡触发、Polymarket 预测市场、资产配置映射。

架构文档 §11.6 MCP 工具 + §14.6 可选扩展（Polymarket）+ §11.4 事件→资产配置映射。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Query

from xqtrader.api.v1.events.schemas import (
    EventAssetAllocationRequest,
    EventDetectRequest,
    EventImpactRequest,
)
from xqtrader.domain.event.models import DetectedEvent
from xqtrader.domain.event.services.event_detector import EventDetector
from xqtrader.domain.event.services.event_thesis_service import EventThesisService
from xqtrader.domain.event.services.market_fear_index_service import (
    MarketFearIndexService,
)
from xqtrader.domain.event.services.polymarket_service import polymarket_service

router = APIRouter(prefix="/events", tags=["事件驱动"])

_detector = EventDetector()
_fear_index_service = MarketFearIndexService()
_thesis_service = EventThesisService()


@router.post(
    "/detect",
    summary="事件检测（两层：关键词 + LLM 精细识别）",
    operation_id="detect_events",
)
async def detect_events(req: EventDetectRequest) -> dict:
    """从新闻/公告库扫描事件，两层检测（关键词快速 + LLM 精细识别）。

    返回事件列表 + 交易信号映射。
    """
    events = await _detector.detect_events(
        symbols=req.symbols,
        event_types=req.event_types,
        days=req.days,
        as_of=req.as_of,
    )
    as_of_str = (req.as_of or date.today()).isoformat()
    return {
        "as_of": as_of_str,
        "events": [_enrich_event(e) for e in events],
    }


@router.get(
    "/fear-index",
    summary="宏观恐慌指数（VIX/OVX/GVZ/US10Y + Fear&Greed 评分）",
    operation_id="get_market_fear_index",
)
async def get_market_fear_index(
    indicators: list[str] | None = Query(
        default=None,
        description="指定指标（如 vix,ovx,gvz,us10y，默认全部）",
    ),
    as_of: date | None = Query(default=None, description="基准日期"),
) -> dict:
    """采集宏观恐慌指数并计算综合 Fear & Greed 评分。"""
    result = await _fear_index_service.get_fear_index(
        indicators=indicators,
        as_of=as_of,
    )
    return result.to_dict()


@router.post(
    "/thesis-impact",
    summary="事件→论点卡影响评估（触发 mark_thesis_stale 或更新 catalysts）",
    operation_id="evaluate_event_impact_on_thesis",
)
async def evaluate_event_impact_on_thesis(req: EventImpactRequest) -> dict:
    """评估事件对标的论点卡的影响，命中证伪条件时触发 mark_thesis_stale。"""
    events = [_parse_event(e) for e in req.events if isinstance(e, dict)]
    result = await _thesis_service.evaluate_impact(
        symbol=req.symbol,
        events=events,
        as_of=req.as_of,
    )
    return result.to_dict()


@router.get(
    "/polymarket",
    summary="Polymarket 预测市场事件查询（前瞻性事件概率）",
    operation_id="get_polymarket_events",
)
async def get_polymarket_events(
    keyword: str | None = Query(default=None, description="关键词过滤"),
    min_volume: float = Query(
        default=1000.0, ge=0.0,
        description="最小成交量阈值（USD）",
    ),
    limit: int = Query(default=10, ge=1, le=50, description="返回事件数上限"),
) -> dict:
    """查询 Polymarket 预测市场事件。

    提供前瞻性事件概率数据（地缘政治/贸易政策/选举等），
    作为 event-monitor 的可选输入。数据源：Polymarket Gamma API。

    采集失败返回空列表（不降级、不 fallback）。
    """
    events = await polymarket_service.get_events(
        keyword=keyword,
        min_volume=min_volume,
        limit=limit,
    )
    return {
        "count": len(events),
        "events": [e.to_dict() for e in events],
    }


@router.post(
    "/asset-allocation-impact",
    summary="事件→资产配置影响评估",
    operation_id="evaluate_asset_allocation_impact",
)
async def evaluate_asset_allocation_impact(req: EventAssetAllocationRequest) -> dict:
    """基于事件类型列表，给出资产配置维度的偏好提示。

    事件→资产配置映射表（domain/event/keywords/event_asset_allocation.yaml）：
    - 利空类（股东减持/退市风险）→ risk_off，减仓高风险资产
    - 利好类（货币宽松/资产重组）→ risk_on，加仓成长股
    - 政策类（监管收紧/产业政策）→ 行业轮动信号
    """
    hints = _thesis_service.evaluate_asset_allocation(req.event_types)
    return {
        "count": len(hints),
        "hints": [h.to_dict() for h in hints],
    }


def _enrich_event(event: DetectedEvent) -> dict[str, Any]:
    """事件 + 交易信号映射。"""
    event_dict = event.to_dict()
    mapping = _detector.get_signal_mapping(event.event_type)
    if mapping:
        event_dict["signal"] = mapping.get("signal")
        event_dict["historical_impact"] = mapping.get("historical_impact")
        event_dict["tracking_advice"] = mapping.get("tracking_advice")
        event_dict["severity"] = mapping.get("severity")
        event_dict["is_bullish"] = mapping.get("is_bullish")
    else:
        event_dict["signal"] = None
        event_dict["historical_impact"] = None
        event_dict["tracking_advice"] = None
        event_dict["severity"] = None
        event_dict["is_bullish"] = None
    return event_dict


def _parse_event(data: dict[str, Any]) -> DetectedEvent:
    """从 dict 解析回 DetectedEvent（用于 thesis-impact 端点）。"""
    news_time = data.get("news_time")
    return DetectedEvent(
        event_category=str(data.get("event_category", "")),
        event_type=str(data.get("event_type", "")),
        symbol=data.get("symbol"),
        title=str(data.get("title", "")),
        news_time=datetime.fromisoformat(news_time) if news_time else None,
        source=data.get("source"),
        matched_keywords=data.get("matched_keywords", []),
        detection_layer=str(data.get("detection_layer", "keyword")),
        confidence=float(data.get("confidence", 1.0)),
        raw_content=data.get("raw_content"),
    )
