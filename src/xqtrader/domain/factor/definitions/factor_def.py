"""因子定义数据类 — 独立模块，避免循环导入。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FactorDefinition:
    """因子定义（不可变，代码声明）。"""

    factor_id: str
    display_name: str
    category: str  # risk/fundamental/technical/quantitative/chan/candlestick/alpha
    group_id: str = ""
    direction: str = "DESC"
    scope: str = "both"
    signal_type: str = "continuous"
    base_factor: str = ""
    dependencies: str = ""
    min_periods: int = 1
    compute_module: str = ""
    params: dict[str, Any] | None = None
    data_origin: str = ""
    compute_engine: str = ""
    update_freq: str = "daily"
    report_lag_days: int = 0
    tags: str = ""
    description: str = ""

    def to_registry_dict(self) -> dict[str, Any]:
        """转换为注册表 upsert 字典（不含运行时状态）。"""
        return {
            "factor_id": self.factor_id,
            "display_name": self.display_name,
            "category": self.category,
            "group_id": self.group_id,
            "direction": self.direction,
            "scope": self.scope,
            "signal_type": self.signal_type,
            "base_factor": self.base_factor,
            "dependencies": self.dependencies,
            "min_periods": self.min_periods,
            "compute_module": self.compute_module,
            "params": self.params,
            "data_origin": self.data_origin,
            "compute_engine": self.compute_engine,
            "update_freq": self.update_freq,
            "report_lag_days": self.report_lag_days,
            "tags": self.tags,
            "description": self.description,
        }
