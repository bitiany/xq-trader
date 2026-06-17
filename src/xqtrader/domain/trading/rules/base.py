"""规则引擎基础类型 — RulePlugin ABC、RuleContext、RuleResult、SelectionScore、UniverseProvider"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    pass


# ==================== 规则执行上下文与结果 ====================

@dataclass
class RuleContext:
    """规则执行上下文 — 传递给每条规则的输入"""

    symbol: str
    signal_date: date
    factor_values: dict[str, float] = field(default_factory=dict)
    factor_series: dict[str, pd.Series] = field(default_factory=dict)
    cross_section_df: pd.DataFrame | None = None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuleResult:
    """规则执行结果 — 每条规则的输出"""

    rule_id: str
    passed: bool = False
    score: float = 0.0
    direction: str = "neutral"
    confidence: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class SelectionScore:
    """选股得分 — 单个标的的最终选股结果"""

    symbol: str
    score: float = 0.0
    direction: str = "long"
    confidence: float = 0.0
    rule_results: list[RuleResult] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


# ==================== RulePlugin ABC ====================

class RulePlugin(ABC):
    """SPI 规则插件基类 — 自定义复杂策略通过继承此基类实现"""

    rule_id: str = ""
    name: str = ""
    category: str = ""  # cross_section / time_series / both
    factor_ids: list[str] = []

    @abstractmethod
    async def evaluate(self, context: RuleContext) -> RuleResult:
        """执行规则评估，返回 RuleResult"""


# ==================== UniverseProvider ====================

class UniverseProvider(ABC):
    """候选标的提供者 — 可插拔的标的范围抽象"""

    @abstractmethod
    async def get_symbols(self) -> list[str]:
        """获取候选标的列表"""

    @abstractmethod
    def describe(self) -> str:
        """描述当前候选池（用于日志）"""


class IndexUniverse(UniverseProvider):
    """指数成分股候选池"""

    def __init__(self, pool_id: str) -> None:
        self.pool_id = pool_id

    async def get_symbols(self) -> list[str]:
        from xqtrader.domain.factor.services.cross_section_reader import CrossSectionReader

        reader = CrossSectionReader()
        return await reader.load_pool_symbols(self.pool_id)

    def describe(self) -> str:
        return f"IndexUniverse(pool_id={self.pool_id})"


class WatchlistUniverse(UniverseProvider):
    """自选池候选池 — 从 trading schema 的 td_watchlist_item 读取"""

    def __init__(self, instance_id: int) -> None:
        self.instance_id = instance_id

    async def get_symbols(self) -> list[str]:
        from xqtrader.domain.trading.models.watchlist import Watchlist, WatchlistItem

        wl = await Watchlist.get_or_none(instance_id=self.instance_id)
        if not wl:
            return []
        items = await WatchlistItem.filter(watchlist_id=wl.id, is_enabled=1)
        return [item.symbol for item in items]

    def describe(self) -> str:
        return f"WatchlistUniverse(instance_id={self.instance_id})"


class FullMarketUniverse(UniverseProvider):
    """全市场候选池"""

    async def get_symbols(self) -> list[str]:
        from xqtrader.domain.factor.services.cross_section_reader import CrossSectionReader

        reader = CrossSectionReader()
        return await reader.load_pool_symbols("all")

    def describe(self) -> str:
        return "FullMarketUniverse()"


class CustomUniverse(UniverseProvider):
    """自定义标的列表候选池"""

    def __init__(self, symbols: list[str]) -> None:
        self._symbols = symbols

    async def get_symbols(self) -> list[str]:
        return self._symbols

    def describe(self) -> str:
        return f"CustomUniverse(n={len(self._symbols)})"
