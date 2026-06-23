"""SPI 规则插件包

预置插件:
  - ExpressionPlugin: 表达式规则插件（默认内置）
  - MACDPlugin: MACD 金叉/死叉规则插件
"""

from .expression import ExpressionPlugin
from .macd import MACDPlugin

__all__ = ["ExpressionPlugin", "MACDPlugin"]
