"""仓位插件包 — 仓位管理插件的统一入口

可用插件:
  - KellyPositionPlugin: 凯利公式仓位管理
  - ATRPositionPlugin: ATR 仓位管理

扩展方式:
  1. 在此目录下新建 .py 文件，继承 PositionPlugin
  2. 在此 __init__.py 中导出
  3. 在策略配置中通过 plugin_class 引用
"""

from .kelly import KellyPositionPlugin
from .atr_position import ATRPositionPlugin

__all__ = ["KellyPositionPlugin", "ATRPositionPlugin"]
