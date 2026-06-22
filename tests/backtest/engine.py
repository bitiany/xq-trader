"""信号引擎 — 策略级多规则聚合

根据 StrategyConfig 初始化 RulePlugin 实例，执行时遍历所有插件聚合结果。
支持两种规则类型:
  - expression: 使用内置 ExpressionPlugin
  - plugin: 动态加载自定义 RulePlugin 子类
"""

import importlib
import logging

from .core import RuleConfig, RuleContext, RuleResult, StrategyConfig, RulePlugin
from .plugins.expression import ExpressionPlugin

logger = logging.getLogger(__name__)


def _load_plugin_class(plugin_class: str) -> type:
    """动态加载插件类

    Args:
        plugin_class: 全限定类名, 如 "tests.backtest.plugins.macd.MACDPlugin"
    """
    module_path, class_name = plugin_class.rsplit(".", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    if not isinstance(cls, type):
        raise TypeError(f"{plugin_class} 不是有效的类")
    if not hasattr(cls, "evaluate") or not hasattr(cls, "factor_ids"):
        raise TypeError(f"{plugin_class} 不符合 RulePlugin 接口（缺少 evaluate 或 factor_ids）")
    return cls


class SignalEngine:
    """信号引擎 — 根据 StrategyConfig 初始化插件，聚合多规则结果

    流程:
      1. 获取策略配置（StrategyConfig）
      2. 为每条 RuleConfig 创建对应的 RulePlugin 实例
      3. 执行时遍历所有插件，聚合结果（任一规则触发即产生信号）
    """

    def __init__(self, strategy_config: StrategyConfig):
        self._config = strategy_config
        self._plugins: list[RulePlugin] = []
        self._init_plugins()

    def _init_plugins(self):
        """根据策略配置创建规则插件实例"""
        for rule_cfg in self._config.rules:
            if rule_cfg.rule_type == "expression":
                self._plugins.append(ExpressionPlugin(rule_cfg))
            elif rule_cfg.rule_type == "plugin":
                cls = _load_plugin_class(rule_cfg.plugin_class)
                self._plugins.append(cls())
            else:
                logger.warning(f"未知规则类型: {rule_cfg.rule_type}")

    def execute(self, context: RuleContext) -> RuleResult:
        """执行所有规则插件，返回聚合结果

        聚合策略: 任一规则触发 buy 则 buy，任一触发 sell 则 sell，
        优先 buy（同时触发时买入优先）
        """
        buy_result = None
        sell_result = None

        for plugin in self._plugins:
            result = plugin.evaluate(context)
            if result.direction == "buy" and buy_result is None:
                buy_result = result
            elif result.direction == "sell" and sell_result is None:
                sell_result = result

        if buy_result:
            return buy_result
        if sell_result:
            return sell_result
        return RuleResult(rule_id=self._config.strategy_id, direction="neutral", reason="无信号")

    @property
    def config(self) -> StrategyConfig:
        return self._config
