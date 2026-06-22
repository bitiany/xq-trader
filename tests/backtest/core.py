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
class StrategyConfig:
    """策略配置 — 一个策略包含多条规则和一个仓位配置"""

    strategy_id: str
    name: str
    rules: list[RuleConfig] = field(default_factory=list)
    position_config: PositionConfig | None = None

    def get_all_factor_ids(self) -> list[str]:
        """获取策略所有规则和仓位插件所需的因子（去重）"""
        seen = set()
        result = []
        for rule in self.rules:
            for fid in rule.factor_ids:
                if fid not in seen:
                    seen.add(fid)
                    result.append(fid)
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
        for rule in self.rules:
            for fid in rule.prev_factor_ids:
                if fid not in seen:
                    seen.add(fid)
                    result.append(fid)
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
