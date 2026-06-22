"""仓位管理基础类型 — PositionSizingStrategy ABC + PortfolioState + SizingContext。

核心设计:
  - PositionSizingStrategy ABC: SPI 插件基类，prepare() 异步预加载 + compute_weights() 同步计算
  - PortfolioState: 环境无关的组合状态，由调用方构建（backtrader 从 broker，实盘从 td_position）
  - SizingContext: prepare() 的上下文，包含回测范围与参数

三环境共用:
  - backtrader: prepare() 预加载 → next() 内构建 PortfolioState → compute_weights()
  - 模拟盘/实盘: prepare() 预加载 → 决策流构建 PortfolioState → compute_weights()
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from ..signals.fusion import FusionResult


@dataclass
class PositionInfo:
    """单标的持仓信息。"""

    symbol: str
    qty: int = 0
    avg_price: float = 0.0
    market_value: float = 0.0
    weight: float = 0.0


@dataclass
class PortfolioState:
    """当前组合状态 — 环境无关，由调用方构建。

    backtrader: 从 self.broker 构建
    模拟盘/实盘: 从 td_position 表构建
    """

    current_date: date
    cash: float = 0.0
    total_value: float = 0.0
    positions: dict[str, PositionInfo] = field(default_factory=dict)


@dataclass
class SizingContext:
    """仓位管理预加载上下文。"""

    symbols: list[str]
    start_date: date
    end_date: date
    params: dict[str, Any] = field(default_factory=dict)
    initial_capital: float = 1_000_000.0


@dataclass
class SizingResult:
    """仓位管理输出 — 单标的目标仓位。"""

    symbol: str
    target_weight: float = 0.0
    target_qty: int | None = None
    current_weight: float | None = None
    sizing_strategy: str = ""
    sizing_params: dict[str, Any] = field(default_factory=dict)
    raw_score: float = 0.0


class PositionSizingStrategy(ABC):
    """仓位管理策略 SPI 基类 — 自定义仓位策略通过继承此基类实现。

    子类需实现:
      - get_config_schema(): 返回配置 schema
      - prepare(): 异步预加载所需数据（ATR/波动率/胜率等）
      - compute_weights(): 同步计算目标权重（纯计算，无 I/O）
    """

    strategy_name: str = ""

    @abstractmethod
    def get_config_schema(self) -> dict[str, Any]:
        """返回策略配置 schema。"""

    @abstractmethod
    async def prepare(self, context: SizingContext) -> None:
        """异步预加载所需数据（ATR/波动率/胜率等）。

        在 backtrader 启动前或决策流开始时调用。
        """

    @abstractmethod
    def compute_weights(
        self,
        signals: dict[str, FusionResult],
        portfolio: PortfolioState,
        market_data: dict[str, pd.DataFrame] | None = None,
    ) -> dict[str, SizingResult]:
        """同步计算目标权重 — 纯计算，无 I/O。

        Args:
            signals: 融合后的信号 {symbol: FusionResult}
            portfolio: 当前组合状态
            market_data: 可选的市场数据（backtrader 可传入当日数据）

        Returns:
            {symbol: SizingResult} 各标的目标仓位
        """
