"""交易域 ORM 模型 — 统一导出"""

from .account import AccountSnapshot, TradingAccount
from .decision import PositionSizingResult, SelectionResult, SignalFusionResult, TradingSignal
from .instance import PaperSession, StrategyInstance
from .order import Order, OrderEvent, PreOrder, Trade
from .position import PositionSnapshot
from .risk import RiskEvent, RiskRule
from .rule import RuleFactorDep, RuleRegistry
from .strategy import Strategy, StrategyRuleBinding, StrategyRuleGroup
from .watchlist import Watchlist, WatchlistItem

__all__ = [
    # 账户 & 快照
    "TradingAccount",
    "AccountSnapshot",
    # 策略实例 & 模拟盘
    "StrategyInstance",
    "PaperSession",
    # 自选池
    "Watchlist",
    "WatchlistItem",
    # 决策流
    "SelectionResult",
    "TradingSignal",
    "SignalFusionResult",
    "PositionSizingResult",
    # 执行流
    "PreOrder",
    "Order",
    "OrderEvent",
    "Trade",
    # 持仓快照
    "PositionSnapshot",
    # 风控
    "RiskRule",
    "RiskEvent",
    # 规则引擎
    "RuleRegistry",
    "RuleFactorDep",
    # 策略引擎
    "Strategy",
    "StrategyRuleGroup",
    "StrategyRuleBinding",
]
