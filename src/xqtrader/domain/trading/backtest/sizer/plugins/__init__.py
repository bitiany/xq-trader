"""仓位管理 SPI 插件包

预置插件:
  - KellyPositionPlugin: 凯利公式仓位
  - ATRPositionPlugin: ATR 风险平价仓位
"""

from .atr_position import ATRPositionPlugin
from .kelly import KellyPositionPlugin

__all__ = ["ATRPositionPlugin", "KellyPositionPlugin"]
