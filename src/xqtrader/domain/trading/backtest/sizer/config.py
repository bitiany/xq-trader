"""仓位配置 — 指定仓位管理插件及其参数"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PositionConfig:
    """仓位配置 — 指定仓位管理插件及其参数

    所有仓位管理均以插件形式实现:
      - plugin_class: 插件全限定类名
      - params: 传递给插件的参数
      - factor_ids: 仓位插件所需的额外因子（与规则因子合并）
    """

    plugin_class: str
    params: dict[str, Any] = field(default_factory=dict)
    factor_ids: list[str] = field(default_factory=list)
