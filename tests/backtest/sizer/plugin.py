"""仓位插件基类 — SPI 扩展点"""

from abc import ABC, abstractmethod

from .context import PositionContext, PositionResult


class PositionPlugin(ABC):
    """仓位管理插件基类 — 通过继承此基类实现不同的仓位管理策略

    子类必须声明:
      - position_id: 唯一标识
      - name: 显示名称
      - factor_ids: 所需因子列表（如 ATR 仓位需要 atr 因子）
    """

    position_id: str = ""
    name: str = ""
    factor_ids: list[str] = []

    @abstractmethod
    def calculate_size(self, context: PositionContext) -> PositionResult:
        """计算仓位大小，返回 PositionResult"""
