"""核心数据结构 — 规则上下文、规则结果、规则配置、策略配置、插件基类"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from .sizer import PositionConfig


@dataclass
class RuleContext:
    """规则执行上下文 — 传递给每条规则的输入"""

    symbol: str
    signal_date: date
    factor_values: dict[str, float] = field(default_factory=dict)
    factor_series: dict[str, pd.Series] = field(default_factory=dict)
    cross_section_df: pd.DataFrame | None = None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuleResult:
    """规则执行结果 — 每条规则的输出"""

    rule_id: str
    passed: bool = False
    score: float = 0.0
    direction: str = "neutral"  # buy | sell | neutral
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
         例: plugin_class="tests.backtest.plugins.MACDPlugin"
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



# ══════════════════════════════════════════════
# 仓位管理 — 已迁移到 sizer 子模块
# PositionContext, PositionResult, PositionPlugin, PositionConfig
# 请从 tests.backtest.sizer 导入
# ══════════════════════════════════════════════


@dataclass
class FusionConfig:
    """融合配置 — 定义规则组内或组间的信号融合方式

    支持五种融合方式:
      - and: 所有规则通过且方向一致才产生信号
      - or: 任一规则触发即产生信号（buy 优先）
      - weighted_score: 加权评分，score × direction 加权求和后与阈值比较
      - weighted_vote: 加权投票，方向投票加权求和后与阈值比较
      - ic_weighted: IC 加权，用历史 IC 值作为权重加权评分

    weights 的 key 为 rule_id（或 group_id），value 为权重值。
    对于 ic_weighted，weights 的 value 为该规则的历史 IC 值。
    """

    method: str = "or"  # and | or | weighted_score | weighted_vote | ic_weighted
    weights: dict[str, float] = field(default_factory=dict)
    buy_threshold: float = 0.5
    sell_threshold: float = 0.5


@dataclass
class RuleGroupConfig:
    """规则组配置 — 一组规则 + 组内融合方式

    规则组是分层组合的基本单元:
      - 组内规则通过 FusionConfig.fusion 融合，产生组级信号
      - 多个组之间通过 StrategyConfig.group_fusion 融合，产生最终信号
    """

    group_id: str
    name: str = ""
    rules: list[RuleConfig] = field(default_factory=list)
    fusion: FusionConfig = field(default_factory=FusionConfig)


@dataclass
class StrategyConfig:
    """策略配置 — 一个策略包含规则组列表和组间融合配置

    支持两种配置方式:
      1. 直接 rules（向后兼容）: 单一规则列表，引擎自动创建隐式规则组（OR 融合）
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
        seen = set()
        result = []

        def _collect(rule: RuleConfig):
            for fid in rule.factor_ids:
                if fid not in seen:
                    seen.add(fid)
                    result.append(fid)

        # 优先从 groups 收集，其次从 rules 收集
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
        seen = set()
        result = []

        def _collect(rule: RuleConfig):
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
      - prev_factor_ids: 需要前一日值的因子（自动注入 {factor}_prev）
    """

    rule_id: str = ""
    name: str = ""
    factor_ids: list[str] = []
    prev_factor_ids: list[str] = []

    @abstractmethod
    def evaluate(self, context: RuleContext) -> RuleResult:
        """执行规则评估，返回 RuleResult"""
