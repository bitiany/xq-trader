"""仓位管理策略包 — 注册所有内置策略到默认注册表。"""

from framework.commons.logger import get_logger

from ..registry import get_default_registry
from .atr_risk import AtrRiskStrategy
from .equal_weight import EqualWeightStrategy
from .fixed_fraction import FixedFractionStrategy
from .inverse_volatility import InverseVolatilityStrategy
from .kelly_fraction import KellyFractionStrategy
from .max_position_cap import MaxPositionCapStrategy
from .signal_weight import SignalWeightStrategy
from .volatility_target import VolatilityTargetStrategy

logger = get_logger(__name__)

# 内置策略列表
_BUILTIN_STRATEGIES = [
    EqualWeightStrategy(),
    SignalWeightStrategy(),
    InverseVolatilityStrategy(),
    VolatilityTargetStrategy(),
    AtrRiskStrategy(),
    KellyFractionStrategy(),
    FixedFractionStrategy(),
    MaxPositionCapStrategy(),
]


def register_builtin_strategies() -> None:
    """注册所有内置仓位策略到默认注册表。"""
    registry = get_default_registry()
    for strategy in _BUILTIN_STRATEGIES:
        if not registry.has(strategy.strategy_name):
            registry.register(strategy)
    logger.info(f"内置仓位策略注册完成: {len(_BUILTIN_STRATEGIES)} 种")


# 模块加载时自动注册
register_builtin_strategies()
