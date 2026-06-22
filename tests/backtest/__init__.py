"""Backtest 测试模块 — 统一导出公共 API"""

from .core import (
    RuleContext, RuleResult, RuleConfig, StrategyConfig, RulePlugin,
)
from .sizer import (
    PositionContext, PositionResult, PositionPlugin, PositionConfig, SizerEngine,
)
from .engine import SignalEngine
from .backtrader_ext import XqTraderStrategy, PluginSizer, create_factor_datafeed
from .strategies import MACD_STRATEGY, MACD_KELLY_STRATEGY, MACD_ATR_STRATEGY, RSI_STRATEGY
from .performance import add_analyzers, extract_performance, print_performance, print_trade_records
from .runner import run_backtest
