"""回测引擎包 — 基于 backtrader 的因子驱动回测。

核心组件:
  - TechnicalIndicatorCalculator: talib 技术指标封装（ATR/MA/MACD/RSI/Bollinger/KDJ）
  - FactorPrecomputer: 回测前预计算因子 + OHLCV + 技术指标，输出 per-symbol DataFrame
  - BacktestBrokerAdapter: 回测券商适配器，包装 backtrader broker
  - FactorDataFeed: 将预计算 DataFrame 注入 backtrader 作为 DataFeed
  - XqTraderStrategy: backtrader 策略，调用 SignalEngine + PositionSizingEngine
  - BacktestEngine: 回测编排器，串联预计算 → 数据注入 → 策略运行 → 绩效收集
  - QuantStatsAnalyzer: QuantStats 绩效分析，指标计算 + HTML 报告 + 中文补丁

设计原则:
  - 回测与截面选股职责分离 — 回测内只做信号→交易→成交
  - 因子与技术指标在回测前一次性预计算，回测中无 I/O
  - SignalEngine / PositionSizingEngine 环境无关，回测/模拟盘/实盘共用
  - BrokerAdapter 协议统一券商接口，三环境各自实现
"""

from __future__ import annotations

from .analyzer import AnalysisReport, PerformanceMetrics, QuantStatsAnalyzer
from .broker_adapter import BacktestBrokerAdapter
from .data_feed import collect_extra_columns, create_data_feed, create_factor_data_feed_class
from .engine import BacktestConfig, BacktestEngine, BacktestResult
from .indicators import IndicatorSpec, TechnicalIndicatorCalculator, parse_indicator_specs
from .precomputer import FactorPrecomputer, PrecomputeConfig
from .strategy import XqTraderStrategy

__all__ = [
    "AnalysisReport",
    "BacktestBrokerAdapter",
    "BacktestConfig",
    "BacktestEngine",
    "BacktestResult",
    "IndicatorSpec",
    "PerformanceMetrics",
    "QuantStatsAnalyzer",
    "TechnicalIndicatorCalculator",
    "parse_indicator_specs",
    "FactorPrecomputer",
    "PrecomputeConfig",
    "create_factor_data_feed_class",
    "create_data_feed",
    "collect_extra_columns",
    "XqTraderStrategy",
]
