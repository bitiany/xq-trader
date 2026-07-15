"""策略择时信号子模块 — 薄包装 SPI 插件 evaluate() 的信号判定能力。"""

from xqtrader.domain.trading.strategy_signal.evaluator import StrategySignalEvaluator
from xqtrader.domain.trading.strategy_signal.registry import (
    StrategyMeta,
    get_strategy_meta,
    list_strategy_names,
)

__all__ = [
    "StrategySignalEvaluator",
    "StrategyMeta",
    "get_strategy_meta",
    "list_strategy_names",
]
