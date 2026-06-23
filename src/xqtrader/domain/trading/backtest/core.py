"""核心数据结构 — 规则上下文、规则结果、规则/策略/融合配置、插件基类

本模块定义回测引擎的核心数据结构，与 backtrader 等具体框架完全解耦。

设计原则:
  - 纯 dataclass，无副作用、无 I/O
  - 配置层（RuleConfig/RuleGroupConfig/StrategyConfig）描述"如何做"
  - 运行时数据（RuleContext/RuleResult）描述"运行时输入输出"
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from .sizer import PositionConfig


@dataclass
class RuleContext:
    """规则执行上下文 — 传递给每条规则的输入

    Fields:
        symbol: 标的代码
        signal_date: 信号日
        factor_values: 当前 bar 的因子值快照
        factor_series: 因子时序数据（可选，规则可访问历史窗口）
        cross_section_df: 同日多标的截面数据（截面选股专用）
        config: 规则运行时配置覆盖
    """

    symbol: str
    signal_date: date
    factor_values: dict[str, float | None] = field(default_factory=dict)
    factor_series: dict[str, pd.Series] = field(default_factory=dict)
    cross_section_df: pd.DataFrame | None = None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuleResult:
    """规则执行结果 — 每条规则的输出

    Fields:
        rule_id: 规则编码
        passed: 是否触发
        score: 得分（强度），范围 [0, 1]
        direction: 方向 — 时序场景 buy/sell/neutral；截面场景 bullish/bearish/neutral
        confidence: 置信度 [0, 1]
        reason: 触发原因文本
        detail: 详细诊断数据（因子值快照等）
    """

    rule_id: str
    passed: bool = False
    score: float = 0.0
    direction: str = "neutral"
    confidence: float = 0.0
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuleConfig:
    """规则配置 — 定义一条规则的类型、依赖因子和参数

    支持两种规则类型:
      1. expression: 表达式规则，通过 buy_expr / sell_expr 定义信号条件
         例: buy_expr="rsi < 30", sell_expr="rsi > 70"
      2. plugin: SPI 插件规则，通过 plugin_class 指定插件全限定类名
         例: plugin_class="xqtrader.domain.trading.backtest.plugins.macd.MACDPlugin"

    Fields:
        rule_id: 规则编码
        rule_type: expression | plugin
        factor_ids: 依赖因子列表
        prev_factor_ids: 需要前值的因子（引擎自动注入 `{factor}_prev`）
        buy_expr / sell_expr: 时序场景表达式
        plugin_class: SPI 插件全限定类名
        params: 插件运行时参数
    """

    rule_id: str
    rule_type: str  # "expression" | "plugin"
    factor_ids: list[str] = field(default_factory=list)
    prev_factor_ids: list[str] = field(default_factory=list)

    # expression 类型参数
    buy_expr: str = ""
    sell_expr: str = ""

    # plugin 类型参数
    plugin_class: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class FusionConfig:
    """融合配置 — 定义规则组内或组间的信号融合方式

    支持五种融合方式:
      - and: 所有规则通过且方向一致才产生信号
      - or: 任一规则触发即产生信号（buy 优先）
      - weighted_score: 加权评分，score × direction 加权求和后与阈值比较
      - weighted_vote: 加权投票，方向投票加权求和后与阈值比较
      - ic_weighted: IC 加权，用历史 IC 值作为权重加权评分

    Fields:
        method: 融合方式
        weights: 权重字典，key=rule_id 或 group_id，value=权重值
                 对于 ic_weighted，value 为该规则的历史 IC 值
        buy_threshold: 触发买入的阈值
        sell_threshold: 触发卖出的阈值
    """

    method: str = "or"
    weights: dict[str, float] = field(default_factory=dict)
    buy_threshold: float = 0.5
    sell_threshold: float = 0.5


@dataclass
class RuleGroupConfig:
    """规则组配置 — 一组规则 + 组内融合方式

    规则组是分层组合的基本单元:
      - 组内规则通过 fusion 融合，产生组级信号
      - 多个组之间通过 StrategyConfig.group_fusion 融合，产生最终信号
    """

    group_id: str
    name: str = ""
    rules: list[RuleConfig] = field(default_factory=list)
    fusion: FusionConfig = field(default_factory=FusionConfig)


@dataclass
class StrategyConfig:
    """策略配置 — 一个策略包含规则组列表和组间融合配置

    配置层不包含运行时参数（标的、日期、资金等），由 API 入参在运行时注入。

    支持两种配置方式:
      1. 直接 rules: 单一规则列表，引擎自动创建隐式规则组（OR 融合）
      2. groups + group_fusion: 多规则组，组内各自融合，组间再用 group_fusion 融合
    """

    strategy_id: str
    name: str
    rules: list[RuleConfig] = field(default_factory=list)
    groups: list[RuleGroupConfig] = field(default_factory=list)
    group_fusion: FusionConfig = field(default_factory=FusionConfig)
    position_config: PositionConfig | None = None

    def get_all_factor_ids(self) -> list[str]:
        """获取策略所有规则和仓位插件所需的因子（去重）"""
        seen: set[str] = set()
        result: list[str] = []

        def _collect(rule: RuleConfig) -> None:
            for fid in rule.factor_ids:
                if fid not in seen:
                    seen.add(fid)
                    result.append(fid)

        for group in self.groups:
            for rule in group.rules:
                _collect(rule)
        for rule in self.rules:
            _collect(rule)

        if self.position_config:
            for fid in self.position_config.factor_ids:
                if fid not in seen:
                    seen.add(fid)
                    result.append(fid)
        return result

    def get_all_prev_factor_ids(self) -> list[str]:
        """获取策略所有规则中需要前值的因子（去重）"""
        seen: set[str] = set()
        result: list[str] = []

        def _collect(rule: RuleConfig) -> None:
            for fid in rule.prev_factor_ids:
                if fid not in seen:
                    seen.add(fid)
                    result.append(fid)

        for group in self.groups:
            for rule in group.rules:
                _collect(rule)
        for rule in self.rules:
            _collect(rule)
        return result


class RulePlugin(ABC):
    """SPI 规则插件基类 — 自定义复杂策略通过继承此基类实现

    子类必须声明:
      - rule_id: 唯一标识
      - name: 显示名称
      - factor_ids: 所需因子列表
      - prev_factor_ids: 需要前一日值的因子（自动注入 `{factor}_prev`）
    """

    rule_id: str = ""
    name: str = ""
    factor_ids: list[str] = []
    prev_factor_ids: list[str] = []

    @abstractmethod
    def evaluate(self, context: RuleContext) -> RuleResult:
        """执行规则评估，返回 RuleResult"""
