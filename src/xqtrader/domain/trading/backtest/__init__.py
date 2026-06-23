"""回测引擎 — backtrader 驱动的时序信号回测

模块组织:
  - core: 核心数据结构（RuleContext/RuleResult/RuleConfig/StrategyConfig/FusionConfig 等）
  - fusion: 信号融合策略（AND/OR/加权评分/加权投票/IC加权）
  - sizer: 仓位管理子模块（插件式架构）
  - plugins: SPI 规则插件（MACD/Expression 等）
  - engine: SignalEngine 信号引擎（分层融合）
  - backtrader_ext: backtrader 适配层（DataFeed/Sizer/Strategy）
  - runner: 回测运行器（编排入口）
  - performance: 绩效分析（backtrader 内置分析器）

设计原则:
  - 配置与运行态分离：策略配置不含标的、日期、资金等运行时参数
  - 截面/时序解耦：回测只处理时序信号，截面选股由外部模块处理
  - 框架无关：核心数据结构与 backtrader 解耦，可适配其他回测框架
"""

from .core import (
    FusionConfig,
    RuleConfig,
    RuleContext,
    RuleGroupConfig,
    RulePlugin,
    RuleResult,
    StrategyConfig,
)
from .engine import SignalEngine
from .sizer import PositionConfig, PositionContext, PositionPlugin, PositionResult, SizerEngine

__all__ = [
    "FusionConfig",
    "PositionConfig",
    "PositionContext",
    "PositionPlugin",
    "PositionResult",
    "RuleConfig",
    "RuleContext",
    "RuleGroupConfig",
    "RulePlugin",
    "RuleResult",
    "SignalEngine",
    "SizerEngine",
    "StrategyConfig",
]
