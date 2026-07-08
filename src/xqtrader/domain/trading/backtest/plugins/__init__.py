"""SPI 规则插件包

预置插件:
  - ExpressionPlugin: 表达式规则插件（默认内置）
  - MACDPlugin: MACD 金叉/死叉规则插件
  - KDJPlugin: KDJ 金叉/死叉规则插件
  - BollingerPlugin: 布林带突破规则插件
  - MACrossPlugin: 双均线交叉规则插件
  - ChanlunPlugin: 缠论买卖点规则插件
  - RSIDivergencePlugin: RSI 背离规则插件
  - VolumePricePlugin: 量价突破规则插件
  - ADXTrendPlugin: ADX 趋势强度规则插件
  - BiasReversalPlugin: BIAS 乖离反转规则插件
  - VolRatioPlugin: 量比突破规则插件
  - TDSequentialPlugin: 神奇九转 TD Sequential 规则插件
  - MomentumPlugin: 动量趋势跟随规则插件
"""

from .adx_trend import ADXTrendPlugin
from .bias_reversal import BiasReversalPlugin
from .bollinger import BollingerPlugin
from .chanlun import ChanlunPlugin
from .expression import ExpressionPlugin
from .kdj import KDJPlugin
from .ma_cross import MACrossPlugin
from .macd import MACDPlugin
from .momentum import MomentumPlugin
from .rsi_divergence import RSIDivergencePlugin
from .td_sequential import TDSequentialPlugin
from .vol_ratio import VolRatioPlugin
from .volume_price import VolumePricePlugin

__all__ = [
    "ExpressionPlugin",
    "MACDPlugin",
    "KDJPlugin",
    "BollingerPlugin",
    "MACrossPlugin",
    "ChanlunPlugin",
    "RSIDivergencePlugin",
    "VolumePricePlugin",
    "ADXTrendPlugin",
    "BiasReversalPlugin",
    "VolRatioPlugin",
    "TDSequentialPlugin",
    "MomentumPlugin",
]
