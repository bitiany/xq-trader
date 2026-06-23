"""仓位管理子模块 — 与回测框架解耦的仓位计算引擎

提供统一的仓位计算接口，可在 backtrader 或其他框架中使用。

核心组件:
  - PositionContext: 仓位计算上下文（输入）
  - PositionResult: 仓位计算结果（输出）
  - PositionPlugin: 仓位插件基类（SPI 扩展点）
  - PositionConfig: 仓位配置
  - SizerEngine: 仓位引擎（统一路由到插件）
  - round_to_lot: 按手数取整工具
"""

from .config import PositionConfig
from .context import PositionContext, PositionResult
from .engine import SizerEngine
from .plugin import PositionPlugin
from .utils import round_to_lot

__all__ = [
    "PositionConfig",
    "PositionContext",
    "PositionPlugin",
    "PositionResult",
    "SizerEngine",
    "round_to_lot",
]
