"""规则组合策略 — 基类"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..base import RuleResult


class CombinationStrategy(ABC):
    """规则组合策略基类"""

    method: str = ""

    @abstractmethod
    def combine(
        self,
        rule_results: list[RuleResult],
        weights: dict[str, float] | None = None,
        params: dict[str, Any] | None = None,
    ) -> RuleResult:
        """组合多条规则结果为一条"""
