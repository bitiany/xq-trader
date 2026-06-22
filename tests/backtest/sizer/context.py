"""仓位计算上下文与结果 — 纯数据结构，与任何回测框架解耦"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PositionContext:
    """仓位计算上下文 — 传递给仓位插件的输入

    框架无关的统一输入，任何回测引擎只需构造此对象即可使用仓位引擎。
    """

    symbol: str
    current_price: float
    available_cash: float
    portfolio_value: float
    factor_values: dict[str, float] = field(default_factory=dict)
    closed_trades: list[dict] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class PositionResult:
    """仓位计算结果 — 框架无关的统一输出"""

    size: int = 0  # 股数（已按手数取整）
    reason: str = ""
