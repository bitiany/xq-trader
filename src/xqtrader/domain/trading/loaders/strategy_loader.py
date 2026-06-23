"""策略配置加载器 — DB Strategy → 内存 StrategyConfig

DB 持久化的 Strategy 模型中 config 字段是 JSONB，本加载器:
  1. 从 td_strategy 加载策略主表
  2. 批量加载 config.groups[].rules[] 引用的 RuleRegistry
  3. 合并 rule 默认 definition + 策略中的覆盖参数
  4. 构造内存 StrategyConfig 对象，供 SignalEngine 直接使用

设计原则:
  - 加载器是 DB 与内存引擎的边界，引擎本体不感知 DB
  - 一次加载多次使用：StrategyConfig 是不可变快照
  - 配置错误尽早抛出（rule_id 未找到 / rule_type 不支持等）
"""

from __future__ import annotations

from framework.commons.logger import get_logger

from ..backtest.core import (
    FusionConfig,
    RuleConfig,
    RuleGroupConfig,
    StrategyConfig,
)
from ..backtest.sizer import PositionConfig
from ..models.rule import RuleRegistry as RuleRegistryModel
from ..models.strategy import Strategy

logger = get_logger(__name__)


class StrategyConfigLoader:
    """加载器：DB Strategy → StrategyConfig"""

    @staticmethod
    async def load(strategy_id: str) -> StrategyConfig:
        """根据 strategy_id 加载策略配置

        Args:
            strategy_id: 策略编码（td_strategy.strategy_id）

        Returns:
            StrategyConfig: 可直接传给 SignalEngine / 回测运行器的内存配置

        Raises:
            ValueError: 策略不存在
        """
        strategy = await Strategy.get_or_none(strategy_id=strategy_id)
        if strategy is None:
            raise ValueError(f"策略不存在: {strategy_id}")

        config_dict = strategy.config or {}
        groups_dict = config_dict.get("groups", [])
        group_fusion_dict = config_dict.get("group_fusion", {})
        position_dict = config_dict.get("position_config")

        # 批量加载 rule_registry
        rule_ids: set[str] = set()
        for group in groups_dict:
            for rule_item in group.get("rules", []):
                if isinstance(rule_item, dict) and rule_item.get("rule_id"):
                    rule_ids.add(rule_item["rule_id"])

        rule_registry_map: dict[str, RuleRegistryModel] = {}
        if rule_ids:
            rule_models = await RuleRegistryModel.filter(rule_id__in=list(rule_ids))
            rule_registry_map = {r.rule_id: r for r in rule_models}

        # 构造 RuleGroupConfig 列表
        groups: list[RuleGroupConfig] = []
        for group_dict in groups_dict:
            rules: list[RuleConfig] = []
            weights: dict[str, float] = {}
            for rule_item in group_dict.get("rules", []):
                if not isinstance(rule_item, dict) or not rule_item.get("rule_id"):
                    continue
                rule_config = StrategyConfigLoader._build_rule_config(rule_item, rule_registry_map)
                if rule_config is None:
                    continue
                rules.append(rule_config)
                weights[rule_config.rule_id] = float(rule_item.get("weight", 1.0))
            if not rules:
                continue

            fusion_dict = group_dict.get("fusion", {})
            fusion = FusionConfig(
                method=fusion_dict.get("method", "or"),
                weights=fusion_dict.get("weights") or weights,
                buy_threshold=fusion_dict.get("buy_threshold", 0.5),
                sell_threshold=fusion_dict.get("sell_threshold", 0.5),
            )

            groups.append(RuleGroupConfig(
                group_id=group_dict.get("group_id", f"group_{len(groups)}"),
                name=group_dict.get("name", ""),
                rules=rules,
                fusion=fusion,
            ))

        group_fusion = FusionConfig(
            method=group_fusion_dict.get("method", "or"),
            weights=group_fusion_dict.get("weights", {}),
            buy_threshold=group_fusion_dict.get("buy_threshold", 0.5),
            sell_threshold=group_fusion_dict.get("sell_threshold", 0.5),
        )

        position_config = None
        if position_dict and position_dict.get("plugin_class"):
            position_config = PositionConfig(
                plugin_class=position_dict["plugin_class"],
                params=position_dict.get("params", {}),
                factor_ids=position_dict.get("factor_ids", []),
            )

        return StrategyConfig(
            strategy_id=strategy.strategy_id,
            name=strategy.name,
            groups=groups,
            group_fusion=group_fusion,
            position_config=position_config,
        )

    @staticmethod
    def _build_rule_config(
        rule_item: dict,
        rule_registry_map: dict[str, RuleRegistryModel],
    ) -> RuleConfig | None:
        """根据 rule_id 从注册表加载规则定义并构造 RuleConfig"""
        rid = rule_item["rule_id"]
        rule_model = rule_registry_map.get(rid)
        if rule_model is None:
            logger.warning(f"规则未找到，跳过: {rid}")
            return None

        definition = rule_model.definition or {}
        factors = list(rule_model.factors or [])
        prev_factors = list(definition.get("prev_factors", []))
        rule_type = rule_model.rule_type

        # 用户在策略中可对规则定义做参数级覆盖
        overrides = rule_item.get("params", {}) or {}

        if rule_type == "expression":
            return RuleConfig(
                rule_id=rid,
                rule_type="expression",
                factor_ids=factors,
                prev_factor_ids=prev_factors,
                buy_expr=overrides.get("buy_expr") or definition.get("buy_expr", "")
                          or definition.get("expr", ""),
                sell_expr=overrides.get("sell_expr") or definition.get("sell_expr", ""),
            )
        if rule_type == "plugin":
            plugin_class = definition.get("plugin_class", "")
            if not plugin_class:
                logger.warning(f"插件规则缺少 plugin_class: {rid}")
                return None
            # 从插件类读取 prev_factor_ids（插件类声明的依赖前值因子）
            plugin_prev_factor_ids = StrategyConfigLoader._get_plugin_prev_factor_ids(plugin_class)
            merged_prev_factors = list(set(prev_factors) | set(plugin_prev_factor_ids))
            return RuleConfig(
                rule_id=rid,
                rule_type="plugin",
                factor_ids=factors,
                prev_factor_ids=merged_prev_factors,
                plugin_class=plugin_class,
                params={**(definition.get("default_params", {})), **overrides},
            )

        logger.warning(f"未知规则类型: {rule_type}, rule_id={rid}")
        return None

    @staticmethod
    def _get_plugin_prev_factor_ids(plugin_class: str) -> list[str]:
        """从插件类读取 prev_factor_ids 类属性"""
        try:
            from ..backtest.engine import _load_plugin_class
            cls = _load_plugin_class(plugin_class)
            return list(getattr(cls, "prev_factor_ids", []))
        except Exception:
            logger.error(f"加载插件类失败，无法读取 prev_factor_ids: {plugin_class}", exc_info=True)
            return []
