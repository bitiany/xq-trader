"""仓位引擎 — 统一路由到不同仓位插件，与回测框架解耦

SizerEngine 是仓位管理的统一入口:
  - 根据 PositionConfig 动态加载插件
  - 提供统一的 calculate 接口，输入 PositionContext，输出 PositionResult
  - 可在任何回测框架中使用，不依赖 backtrader
"""

import importlib
import logging

from .context import PositionContext, PositionResult
from .plugin import PositionPlugin
from .config import PositionConfig
from .utils import round_to_lot

logger = logging.getLogger(__name__)


class SizerEngine:
    """仓位管理引擎 — 高内聚松耦合，与 backtrader 解耦

    职责:
      1. 根据 PositionConfig 动态加载 PositionPlugin
      2. 聚合插件所需因子列表
      3. 提供统一的 calculate() 接口

    使用方式:
      engine = SizerEngine(PositionConfig(
          plugin_class="tests.backtest.sizer.plugins.kelly.KellyPositionPlugin",
          params={"kelly_fraction": 0.5},
      ))
      result = engine.calculate(context)
    """

    def __init__(self, config: PositionConfig | None = None):
        self._config = config
        self._plugin: PositionPlugin | None = None

        if config is not None:
            self._plugin = self._load_plugin(config.plugin_class, config.params)

    @staticmethod
    def _load_plugin(plugin_class: str, params: dict) -> PositionPlugin:
        """动态加载仓位插件并实例化"""
        module_path, class_name = plugin_class.rsplit(".", 1)
        module = importlib.import_module(module_path)
        cls = getattr(module, class_name)
        if not isinstance(cls, type):
            raise TypeError(f"{plugin_class} 不是有效的类")
        if not hasattr(cls, "calculate_size"):
            raise TypeError(f"{plugin_class} 不符合 PositionPlugin 接口（缺少 calculate_size）")
        return cls(params=params)

    @property
    def plugin(self) -> PositionPlugin | None:
        """当前加载的仓位插件"""
        return self._plugin

    @property
    def factor_ids(self) -> list[str]:
        """当前插件所需的因子列表"""
        if self._plugin is not None:
            return list(self._plugin.factor_ids)
        return []

    def calculate(self, context: PositionContext) -> PositionResult:
        """计算仓位大小 — 统一入口

        Args:
            context: 仓位计算上下文（框架无关）

        Returns:
            PositionResult: 仓位计算结果（框架无关）
        """
        if self._plugin is None:
            # 无插件时默认 95% 可用资金
            cash = context.available_cash
            price = context.current_price
            size = round_to_lot(cash * 0.95 / price)
            return PositionResult(
                size=size,
                reason=f"默认仓位: 95%可用资金, 仓位={size}股",
            )

        result = self._plugin.calculate_size(context)
        logger.info(f"仓位计算: {result.reason}")
        return result
