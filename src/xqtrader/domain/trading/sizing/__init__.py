"""仓位管理模块 — 环境无关的仓位管理 SPI 框架。"""

# 导入策略包以触发自动注册
from . import strategies  # noqa: F401
from .base import (
    PortfolioState,
    PositionInfo,
    PositionSizingStrategy,
    SizingContext,
    SizingResult,
)
from .constraints import PortfolioConstraints
from .engine import PositionSizingEngine
from .registry import PositionSizingRegistry, get_default_registry

__all__ = [
    "PositionSizingStrategy",
    "PositionSizingRegistry",
    "PositionSizingEngine",
    "PortfolioConstraints",
    "PortfolioState",
    "PositionInfo",
    "SizingContext",
    "SizingResult",
    "get_default_registry",
]
