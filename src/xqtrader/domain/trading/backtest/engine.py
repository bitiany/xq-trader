"""信号引擎 — 策略级多规则聚合

根据 StrategyConfig 初始化 RulePlugin 实例，执行时遍历所有插件聚合结果。
支持两种规则类型:
  - expression: 使用内置 ExpressionPlugin
  - plugin: 动态加载自定义 RulePlugin 子类

支持两种配置方式:
  1. 直接 rules: 单一规则列表，引擎自动创建隐式规则组（OR 融合）
  2. groups + group_fusion: 多规则组，组内各自融合，组间再用 group_fusion 融合
"""

import importlib
import logging

from .core import RuleConfig, RuleContext, RuleGroupConfig, RulePlugin, RuleResult, StrategyConfig
from .fusion import FusionEngine
from .plugins.expression import ExpressionPlugin

logger = logging.getLogger(__name__)


def _load_plugin_class(plugin_class: str) -> type:
    """动态加载插件类

    Args:
        plugin_class: 全限定类名, 如 "xqtrader.domain.trading.backtest.plugins.macd.MACDPlugin"
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
      3. 执行时遍历所有插件，通过 FusionEngine 融合结果

    支持分层组合:
      - 组内: 各规则结果通过 group.fusion 融合
      - 组间: 各组结果通过 strategy_config.group_fusion 融合
    """

    def __init__(self, strategy_config: StrategyConfig) -> None:
        self._config = strategy_config
        self._fusion_engine = FusionEngine()
        self._groups: list[tuple[RuleGroupConfig, list[RulePlugin]]] = []
        self._init_groups()

    def _init_groups(self) -> None:
        """根据策略配置创建规则组和插件实例"""
        if self._config.groups:
            for group_cfg in self._config.groups:
                plugins = self._create_plugins(group_cfg.rules)
                self._groups.append((group_cfg, plugins))
        elif self._config.rules:
            # 无 groups 时，将 rules 包装为隐式规则组（OR 融合）
            implicit_group = RuleGroupConfig(
                group_id="default",
                name="默认组",
                rules=self._config.rules,
            )
            plugins = self._create_plugins(self._config.rules)
            self._groups.append((implicit_group, plugins))

    @staticmethod
    def _create_plugins(rule_configs: list[RuleConfig]) -> list[RulePlugin]:
        """为规则配置列表创建对应的插件实例"""
        plugins: list[RulePlugin] = []
        for rule_cfg in rule_configs:
            if rule_cfg.rule_type == "expression":
                plugins.append(ExpressionPlugin(rule_cfg))
            elif rule_cfg.rule_type == "plugin":
                cls = _load_plugin_class(rule_cfg.plugin_class)
                plugins.append(cls())
            else:
                logger.warning(f"未知规则类型: {rule_cfg.rule_type}, rule_id={rule_cfg.rule_id}")
        return plugins

    def execute(self, context: RuleContext) -> RuleResult:
        """执行所有规则插件，返回融合后的结果

        流程:
          1. 单组: 组内规则执行 → 组内融合 → 返回
          2. 多组: 各组内融合 → 组间融合 → 返回
        """
        if not self._groups:
            return RuleResult(
                rule_id=self._config.strategy_id,
                direction="neutral",
                reason="无规则配置",
            )

        # 单组: 直接返回组内融合结果
        if len(self._groups) == 1:
            group_cfg, plugins = self._groups[0]
            results = [p.evaluate(context) for p in plugins]
            return self._fusion_engine.fuse(results, group_cfg.fusion)

        # 多组: 先组内融合，再组间融合
        group_results: list[RuleResult] = []
        for group_cfg, plugins in self._groups:
            results = [p.evaluate(context) for p in plugins]
            group_result = self._fusion_engine.fuse(results, group_cfg.fusion)
            # 用 group_id 标识组级结果，供组间融合的 weights 引用
            group_result.rule_id = group_cfg.group_id
            group_results.append(group_result)

        return self._fusion_engine.fuse(group_results, self._config.group_fusion)

    @property
    def config(self) -> StrategyConfig:
        return self._config
