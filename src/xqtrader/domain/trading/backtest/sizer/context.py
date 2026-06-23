"""仓位计算上下文与结果 — 纯数据结构，与任何回测框架解耦"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PositionContext:
    """仓位计算上下文 — 传递给仓位插件的输入

    框架无关的统一输入，任何回测引擎只需构造此对象即可使用仓位引擎。

    Fields:
        symbol: 标的代码
        current_price: 当前价格
        available_cash: 可用资金
        portfolio_value: 组合总价值（现金+持仓市值）
        factor_values: 因子值快照（如 ATR 仓位需要 atr）
        closed_trades: 历史已平仓交易记录（凯利公式仓位需要）
        config: 仓位运行时配置覆盖
    """

    symbol: str
    current_price: float
    available_cash: float
    portfolio_value: float
    factor_values: dict[str, float | None] = field(default_factory=dict)
    closed_trades: list[dict] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class PositionResult:
    """仓位计算结果 — 框架无关的统一输出

    Fields:
        size: 股数（已按手数取整）
        reason: 计算依据的可读说明
    """

    size: int = 0
    reason: str = ""
