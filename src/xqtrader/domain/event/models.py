"""事件检测数据模型 — 事件、事件信号、恐慌指数。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass
class DetectedEvent:
    """检测到的事件 — EventDetector 输出单元。

    Attributes:
        event_category: 事件大类（利好/利空/政策）
        event_type: 事件类型（资产重组/股东减持/货币宽松 等）
        symbol: 关联标的（宏观政策事件可为空）
        title: 新闻/公告标题
        news_time: 发布时间
        source: 来源（如 东方财富/巨潮网）
        matched_keywords: 命中的关键词列表（Layer 1 命中时填充）
        detection_layer: 检测层级（keyword=Layer 1 / llm=Layer 2）
        confidence: 置信度 0-1（Layer 1 关键词命中=1.0，Layer 2 LLM 判定=模型返回）
        raw_content: 原文内容片段（供后续分析）
    """

    event_category: str
    event_type: str
    symbol: str | None
    title: str
    news_time: datetime | None
    source: str | None
    matched_keywords: list[str] = field(default_factory=list)
    detection_layer: str = "keyword"
    confidence: float = 1.0
    raw_content: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_category": self.event_category,
            "event_type": self.event_type,
            "symbol": self.symbol,
            "title": self.title,
            "news_time": self.news_time.isoformat() if self.news_time else None,
            "source": self.source,
            "matched_keywords": self.matched_keywords,
            "detection_layer": self.detection_layer,
            "confidence": self.confidence,
            "raw_content": self.raw_content,
        }


@dataclass
class EventSignal:
    """事件信号 — 事件→交易信号映射结果。

    Attributes:
        event: 原始检测事件
        signal: 交易信号（强烈关注/看多/谨慎/看空/强烈回避/利好/利空）
        reason: 信号生成原因
        severity: 严重程度 1-5
        is_bullish: 是否利好
        historical_impact: 历史统计影响描述
        tracking_advice: 跟踪建议
    """

    event: DetectedEvent
    signal: str
    reason: str
    severity: int
    is_bullish: bool
    historical_impact: str
    tracking_advice: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event.to_dict(),
            "signal": self.signal,
            "reason": self.reason,
            "severity": self.severity,
            "is_bullish": self.is_bullish,
            "historical_impact": self.historical_impact,
            "tracking_advice": self.tracking_advice,
        }


@dataclass
class MarketFearIndex:
    """宏观恐慌指数快照 — MarketFearIndexService 输出。

    Attributes:
        as_of: 快照日期
        vix: VIX 指数值（美股恐慌指数）
        vix_level: VIX 水平判定（极度平静/平静/焦虑/恐慌/极度恐慌）
        ovx: OVX 原油波动率指数
        gvz: GVZ 黄金波动率指数
        us10y: 美 10 年期国债收益率（%）
        us10y_level: US10Y 水平判定（利价值股/分水岭/利成长股）
        cn_limit_up: A 股涨停家数
        cn_limit_down: A 股跌停家数
        cn_advance_decline_ratio: A 股涨跌停家数比
        cn_market_activity: A 股市场活跃度指数（乐咕乐股）
        cn_weibo_hot: 微博财经舆情热度
        fear_greed_score: 综合恐慌/贪婪评分 0-100
        fear_greed_level: 评分水平判定（极度恐慌/恐慌/中性/贪婪/极度贪婪）
        risk_transmission: 风险传导分析
        advice: 操作建议
    """

    as_of: date
    vix: float | None
    vix_level: str
    ovx: float | None
    gvz: float | None
    us10y: float | None
    us10y_level: str
    cn_limit_up: int | None
    cn_limit_down: int | None
    cn_advance_decline_ratio: float | None
    cn_market_activity: float | None
    cn_weibo_hot: float | None
    fear_greed_score: int
    fear_greed_level: str
    risk_transmission: str
    advice: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "vix": self.vix,
            "vix_level": self.vix_level,
            "ovx": self.ovx,
            "gvz": self.gvz,
            "us10y": self.us10y,
            "us10y_level": self.us10y_level,
            "cn_limit_up": self.cn_limit_up,
            "cn_limit_down": self.cn_limit_down,
            "cn_advance_decline_ratio": self.cn_advance_decline_ratio,
            "cn_market_activity": self.cn_market_activity,
            "cn_weibo_hot": self.cn_weibo_hot,
            "fear_greed_score": self.fear_greed_score,
            "fear_greed_level": self.fear_greed_level,
            "risk_transmission": self.risk_transmission,
            "advice": self.advice,
        }


@dataclass
class ThesisImpactResult:
    """事件→论点卡影响评估结果。

    Attributes:
        symbol: 标的代码
        thesis_status: 论点卡状态（active/stale/none=无论点卡）
        triggered_rules: 命中的失效规则列表
        action: 建议动作（mark_thesis_stale / update_catalysts / none）
        reason: 动作原因
    """

    symbol: str
    thesis_status: str
    triggered_rules: list[str]
    action: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "thesis_status": self.thesis_status,
            "triggered_rules": self.triggered_rules,
            "action": self.action,
            "reason": self.reason,
        }


@dataclass
class PolymarketEvent:
    """Polymarket 预测市场事件 — 前瞻性事件概率数据。

    架构文档 §14.6 可选扩展：作为 event-monitor 的可选输入。

    Attributes:
        question: 市场问题（如 "Will Bitcoin reach $100k by 2026?"）
        yes_pct: Yes 概率（0-1，市场隐含概率）
        volume: 累计成交量（USD）
        liquidity: 流动性（USD，可选）
        end_date: 市场结束日期（ISO 格式字符串，可选）
        url: Polymarket 页面 URL
        category: 分类标签（如 "Crypto" / "Politics" / "Economics"）
        slug: 事件 slug（唯一标识）
    """

    question: str
    yes_pct: float
    volume: float
    liquidity: float | None = None
    end_date: str | None = None
    url: str | None = None
    category: str | None = None
    slug: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "yes_pct": self.yes_pct,
            "volume": self.volume,
            "liquidity": self.liquidity,
            "end_date": self.end_date,
            "url": self.url,
            "category": self.category,
            "slug": self.slug,
        }


@dataclass
class AssetAllocationHint:
    """事件→资产配置影响提示 — 架构文档 §11.4 事件→资产配置映射。

    基于事件类型与方向，给出资产配置维度的偏好提示，供 Agent 在策略汇总时参考。

    Attributes:
        event_type: 事件类型（如 股东减持 / 货币宽松 / 退市风险）
        affected_dimension: 影响维度（大盘风格 / 行业轮动 / 风险偏好 / 流动性）
        direction: 配置方向（risk_on / risk_off / defensive / aggressive）
        suggested_weight_change: 建议权重调整方向（+ / - / 0）
        rationale: 配置建议依据
    """

    event_type: str
    affected_dimension: str
    direction: str
    suggested_weight_change: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "affected_dimension": self.affected_dimension,
            "direction": self.direction,
            "suggested_weight_change": self.suggested_weight_change,
            "rationale": self.rationale,
        }
