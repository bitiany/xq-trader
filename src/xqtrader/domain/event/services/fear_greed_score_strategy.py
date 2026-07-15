"""Fear & Greed 综合评分策略 — 策略模式实现。

架构文档 §11.3.2 评分逻辑 + 项目规则"策略模式：条件分支逻辑须封装为策略类 + 注册表"。

设计原则：
  - 每个评分维度封装为独立的策略类（单一职责）
  - 策略注册表统一管理（避免长串 if/elif）
  - 策略无状态，可并发调用
  - 新增维度只需新增策略类 + 注册，无需修改现有代码（开闭原则）

评分公式：score = 50 + Σ(各维度调整值)，最终钳制到 [0, 100]
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class FearGreedScoreStrategy(ABC):
    """评分策略抽象基类。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称（如 vix / us10y / cn_advance_decline）。"""

    @abstractmethod
    def adjust(self, snapshot: dict[str, Any]) -> int:
        """根据快照数据计算评分调整值。

        Args:
            snapshot: 含各维度指标的 dict

        Returns:
            评分调整值（正=贪婪方向，负=恐慌方向，0=无影响）
        """


class VixScoreStrategy(FearGreedScoreStrategy):
    """VIX 美股恐慌指数评分策略。"""

    @property
    def name(self) -> str:
        return "vix"

    def adjust(self, snapshot: dict[str, Any]) -> int:
        vix = snapshot.get("vix")
        if vix is None:
            return 0
        if vix < 15:
            return 30
        if vix < 20:
            return 15
        if vix < 25:
            return 0
        if vix < 35:
            return -15
        return -30


class Us10yScoreStrategy(FearGreedScoreStrategy):
    """美 10 年期国债收益率评分策略。"""

    @property
    def name(self) -> str:
        return "us10y"

    def adjust(self, snapshot: dict[str, Any]) -> int:
        us10y = snapshot.get("us10y")
        if us10y is None:
            return 0
        if us10y < 3.8:
            return 10
        if us10y > 4.8:
            return -10
        return 0


class AdvanceDeclineRatioStrategy(FearGreedScoreStrategy):
    """A 股涨跌停家数比评分策略。

    涨跌停比 > 5 → 市场极度贪婪（追涨情绪强烈）→ +20
    涨跌停比 2-5 → 市场偏贪婪 → +10
    涨跌停比 0.5-2 → 中性 → 0
    涨跌停比 0.2-0.5 → 市场偏恐慌 → -10
    涨跌停比 < 0.2 → 市场极度恐慌（跌停潮）→ -20
    """

    @property
    def name(self) -> str:
        return "cn_advance_decline"

    def adjust(self, snapshot: dict[str, Any]) -> int:
        ratio = snapshot.get("advance_decline_ratio")
        if ratio is None:
            return 0
        if ratio > 5:
            return 20
        if ratio > 2:
            return 10
        if ratio > 0.5:
            return 0
        if ratio > 0.2:
            return -10
        return -20


class MarketActivityStrategy(FearGreedScoreStrategy):
    """A 股市场活跃度评分策略。

    活跃度 > 80 → 极度活跃（贪婪）→ +15
    活跃度 60-80 → 偏活跃 → +8
    活跃度 40-60 → 中性 → 0
    活跃度 20-40 → 偏冷清 → -8
    活跃度 < 20 → 极度冷清（恐慌）→ -15
    """

    @property
    def name(self) -> str:
        return "cn_market_activity"

    def adjust(self, snapshot: dict[str, Any]) -> int:
        activity = snapshot.get("market_activity")
        if activity is None:
            return 0
        if activity > 80:
            return 15
        if activity > 60:
            return 8
        if activity > 40:
            return 0
        if activity > 20:
            return -8
        return -15


class WeiboSentimentStrategy(FearGreedScoreStrategy):
    """微博财经舆情热度评分策略。

    微博舆情热度反映散户情绪温度：
    热度 > 80（高位） → 散户过度乐观（反向指标，贪婪）→ +10
    热度 50-80 → 偏热 → +5
    热度 30-50 → 中性 → 0
    热度 10-30 → 偏冷 → -5
    热度 < 10（低位） → 散户恐慌（反向指标，恐慌）→ -10
    """

    @property
    def name(self) -> str:
        return "cn_weibo_sentiment"

    def adjust(self, snapshot: dict[str, Any]) -> int:
        weibo = snapshot.get("weibo_hot")
        if weibo is None:
            return 0
        if weibo > 80:
            return 10
        if weibo > 50:
            return 5
        if weibo > 30:
            return 0
        if weibo > 10:
            return -5
        return -10


# 策略注册表
_STRATEGIES: list[FearGreedScoreStrategy] = [
    VixScoreStrategy(),
    Us10yScoreStrategy(),
    AdvanceDeclineRatioStrategy(),
    MarketActivityStrategy(),
    WeiboSentimentStrategy(),
]


def compute_fear_greed_score(snapshot: dict[str, Any]) -> int:
    """综合评分：基准分 50 + 各策略调整值之和，钳制到 [0, 100]。

    Args:
        snapshot: 含各维度指标的 dict（缺失维度自动跳过，调整值为 0）

    Returns:
        综合评分 0-100
    """
    score = 50
    for strategy in _STRATEGIES:
        adjustment = strategy.adjust(snapshot)
        score += adjustment
    return max(0, min(100, score))


def classify_score(score: int) -> str:
    """评分水平判定。"""
    if score >= 75:
        return "极度贪婪"
    if score >= 55:
        return "贪婪"
    if score >= 45:
        return "中性"
    if score >= 25:
        return "恐慌"
    return "极度恐慌"
