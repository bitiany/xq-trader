"""规则插件包 — 规则插件的统一入口

规则插件:
  - ExpressionPlugin: 表达式规则（内置默认）
  - MACDPlugin: MACD 金叉死叉规则（自定义）

仓位插件已迁移到 sizer.plugins 子模块:
  - KellyPositionPlugin → tests.backtest.sizer.plugins.kelly
  - ATRPositionPlugin → tests.backtest.sizer.plugins.atr_position

扩展方式:
  1. 在此目录下新建 .py 文件，继承 RulePlugin
  2. 在此 __init__.py 中导出
  3. 在 strategies.py 中通过 plugin_class 引用
"""

from .expression import ExpressionPlugin
from .macd import MACDPlugin

__all__ = ["ExpressionPlugin", "MACDPlugin"]
