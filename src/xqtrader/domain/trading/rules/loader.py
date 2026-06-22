"""规则加载器 — 从 DB 加载规则定义并注册到 RuleRegistry。

SelectionEngine 与 SignalEngine 共用此模块，避免重复逻辑。
"""

from __future__ import annotations

import importlib

from framework.commons.logger import get_logger

from ..models.rule import RuleRegistry as RuleRegistryModel
from ..models.strategy import StrategyRuleBinding
from .registry import RuleRegistry

logger = get_logger(__name__)


class RuleLoader:
    """规则加载器 — 批量加载规则定义并注册到 RuleRegistry。"""

    @staticmethod
    async def ensure_registered(
        registry: RuleRegistry,
        bindings: list[StrategyRuleBinding],
    ) -> None:
        """确保规则已注册到内存注册表（批量查询，避免 N+1）。"""
        missing_rule_ids = list({
            b.rule_id for b in bindings if not registry.has(b.rule_id)
        })
        if not missing_rule_ids:
            return

        rule_models = await RuleRegistryModel.filter(rule_id__in=missing_rule_ids)
        found_ids = {r.rule_id for r in rule_models}

        for rule_id in missing_rule_ids:
            if rule_id not in found_ids:
                logger.warning(f"规则未找到: {rule_id}")

        for rule_model in rule_models:
            if rule_model.type == "expression":
                registry.register_expression(
                    rule_id=rule_model.rule_id,
                    name=rule_model.name,
                    category=rule_model.category,
                    expression=rule_model.expression or "",
                    signal_mapping=rule_model.signal_mapping or {},
                    default_config=rule_model.default_config or {},
                )
            elif rule_model.type == "spi" and rule_model.spi_class:
                RuleLoader.load_spi_plugin(registry, rule_model.spi_class)

    @staticmethod
    def load_spi_plugin(registry: RuleRegistry, spi_class_path: str) -> None:
        """动态加载 SPI 插件并注册。"""
        try:
            module_path, class_name = spi_class_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            plugin_class = getattr(module, class_name)
            plugin = plugin_class()
            registry.register_plugin(plugin)
        except (ImportError, AttributeError) as e:
            logger.error(f"SPI 插件加载失败: {spi_class_path} error={e}", exc_info=True)
