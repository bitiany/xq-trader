"""仓位管理策略注册表 — 管理所有仓位策略实例。"""

from __future__ import annotations

from typing import Any

from framework.commons.logger import get_logger

from .base import PositionSizingStrategy

logger = get_logger(__name__)


class PositionSizingRegistry:
    """仓位管理策略注册表 — 统一管理内置策略与自定义 SPI 插件。"""

    def __init__(self) -> None:
        self._strategies: dict[str, PositionSizingStrategy] = {}

    def register(self, strategy: PositionSizingStrategy) -> None:
        """注册仓位管理策略。"""
        if not strategy.strategy_name:
            msg = f"策略未设置 strategy_name: {type(strategy).__name__}"
            raise ValueError(msg)
        self._strategies[strategy.strategy_name] = strategy
        logger.debug(f"注册仓位策略: {strategy.strategy_name}")

    def get(self, strategy_name: str) -> PositionSizingStrategy:
        """获取策略实例。"""
        if strategy_name not in self._strategies:
            msg = f"仓位策略不存在: {strategy_name}"
            raise KeyError(msg)
        return self._strategies[strategy_name]

    def has(self, strategy_name: str) -> bool:
        """检查策略是否存在。"""
        return strategy_name in self._strategies

    def list_strategies(self) -> list[dict[str, Any]]:
        """列出所有已注册策略。"""
        return [
            {
                "strategy_name": s.strategy_name,
                "type": type(s).__name__,
                "config_schema": s.get_config_schema(),
            }
            for s in self._strategies.values()
        ]


# 全局默认注册表实例
_default_registry = PositionSizingRegistry()


def get_default_registry() -> PositionSizingRegistry:
    """获取全局默认注册表。"""
    return _default_registry
