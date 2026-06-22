"""仓位管理引擎 — 环境无关，编排策略选择 → 计算 → 约束。

核心设计:
  - prepare() 异步初始化：解析策略配置 → 创建仓位策略 → 预加载数据
  - compute_weights() 同步计算：调用策略 → 施加约束 → 返回目标仓位

三环境共用:
  - backtrader: prepare() → next() 内构建 PortfolioState → compute_weights()
  - 模拟盘/实盘: prepare() → 决策流构建 PortfolioState → compute_weights()
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from framework.commons.logger import get_logger

from ..models.strategy import Strategy
from ..signals.fusion import FusionResult
from .base import PortfolioState, PositionSizingStrategy, SizingContext, SizingResult
from .constraints import PortfolioConstraints
from .registry import PositionSizingRegistry, get_default_registry

logger = get_logger(__name__)

# 默认仓位策略
_DEFAULT_STRATEGY = "equal_weight"


class PositionSizingEngine:
    """仓位管理引擎 — 环境无关，可被 backtrader/模拟盘/实盘调用。

    用法:
        engine = PositionSizingEngine(strategy)
        await engine.prepare(sizing_context)
        # backtrader next() 或决策流内:
        results = engine.compute_weights(signals, portfolio)
    """

    def __init__(
        self,
        strategy: Strategy,
        registry: PositionSizingRegistry | None = None,
    ) -> None:
        self._strategy = strategy
        self._registry = registry or get_default_registry()
        self._sizing: PositionSizingStrategy | None = None
        self._constraints: PortfolioConstraints | None = None

    async def prepare(self, context: SizingContext) -> None:
        """异步初始化 — 解析配置、创建策略、预加载数据、设置约束。"""
        config = self._strategy.position_sizing_config or {}
        strategy_name = config.get("strategy", _DEFAULT_STRATEGY)
        params = config.get("params", {})

        if not self._registry.has(strategy_name):
            logger.warning(
                f"仓位策略未注册: {strategy_name}，回退到 {_DEFAULT_STRATEGY}"
            )
            strategy_name = _DEFAULT_STRATEGY

        self._sizing = self._registry.get(strategy_name)
        sizing_context = SizingContext(
            symbols=context.symbols,
            start_date=context.start_date,
            end_date=context.end_date,
            params={**params, **context.params},
            initial_capital=context.initial_capital,
        )
        await self._sizing.prepare(sizing_context)

        constraints_config = config.get("constraints", {})
        self._constraints = PortfolioConstraints(constraints_config)

        logger.info(
            f"PositionSizingEngine prepared | strategy={self._strategy.strategy_id} | "
            f"sizing={strategy_name} | constraints={constraints_config}"
        )

    def compute_weights(
        self,
        signals: dict[str, FusionResult],
        portfolio: PortfolioState,
        market_data: dict[str, pd.DataFrame] | None = None,
    ) -> dict[str, SizingResult]:
        """同步计算目标权重 — 调用策略 + 施加约束。"""
        if self._sizing is None:
            msg = "仓位引擎未初始化，请先调用 prepare()"
            raise RuntimeError(msg)

        # 仅对有信号的标的计算仓位
        active_signals = {
            symbol: signal
            for symbol, signal in signals.items()
            if signal.direction != "neutral"
        }

        if not active_signals:
            return self._build_empty_results(signals, portfolio)

        results = self._sizing.compute_weights(active_signals, portfolio, market_data)

        # 填充当前权重
        for symbol, result in results.items():
            pos = portfolio.positions.get(symbol)
            result.current_weight = pos.weight if pos else 0.0
            result.sizing_strategy = self._sizing.strategy_name

        if self._constraints:
            results = self._constraints.apply(results, portfolio)

        return results

    @staticmethod
    def _build_empty_results(
        signals: dict[str, FusionResult],
        portfolio: PortfolioState,
    ) -> dict[str, SizingResult]:
        """无活跃信号时，返回清仓结果。"""
        results: dict[str, SizingResult] = {}
        for symbol in signals:
            pos = portfolio.positions.get(symbol)
            results[symbol] = SizingResult(
                symbol=symbol,
                target_weight=0.0,
                current_weight=pos.weight if pos else 0.0,
                sizing_strategy="empty",
            )
        return results
