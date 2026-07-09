"""因子领域基础类 — FactorDefinition 与 FactorPlugin。

FactorDefinition: 因子元数据声明（数据类，代码为唯一真相源）
FactorPlugin: 因子计算策略基类（抽象类，子类实现 compute()）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd


@dataclass
class FactorDefinition:
    """因子元数据声明 — 代码为唯一真相源，启动时同步到 fac_factor_registry。

    正交维度（见 docs/factor-system-design.md §3.3）：
      - compute_mode: precomputed（预计算落库）/ on_demand（消费时实时计算）
      - density: dense（日频稠密）/ sparse（事件稀疏）/ discrete（离散信号）
      - usage: cross_section（截面选股）/ time_series（时序回测）/ both
      - preprocess_policy: cross_section_standard（截面标准化）/ raw（不预处理）
    """

    factor_id: str
    display_name: str
    category: str
    group_id: str = ""
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    base_factor: str = ""
    dependencies: list[str] = field(default_factory=list)
    min_periods: int = 1
    requires_full_history: bool = False
    compute_module: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    data_origin: str = ""
    data_start_date: date | None = None
    update_freq: str = "daily"
    compute_engine: str = "plugin"
    report_lag_days: int = 0
    tags: str = ""
    status: str = "active"
    description: str = ""
    is_composite: bool = False
    composite_factor_ids: list[str] = field(default_factory=list)
    child_display_names: dict[str, str] = field(default_factory=dict)
    compute_mode: str = "precomputed"
    density: str = "dense"
    preprocess_policy: str = "cross_section_standard"
    composite_method: str = ""


class FactorPlugin(ABC):
    """因子计算策略基类 — 子类实现 compute()，通过策略模式注册。

    因子分类：
      - 逐标的因子：仅依赖自身时序数据，在因子计算任务中逐标的独立计算
      - 截面因子：依赖全市场截面数据，不在因子计算任务中处理

    组合因子（如 MACD 输出 dif/dea/hist）：
      - is_composite = True
      - composite_factor_ids 列出所有输出因子 ID
      - compute() 返回多列 DataFrame
    """

    factor_id: str = ""
    display_name: str = ""
    category: str = ""
    group_id: str = ""
    direction: str = "DESC"
    usage: str = "both"
    signal_type: str = "continuous"
    base_factor: str = ""
    dependencies: list[str] = ["close"]
    min_periods: int = 1
    requires_full_history: bool = False
    params: dict[str, Any] = {}
    is_composite: bool = False
    composite_factor_ids: list[str] = []
    child_display_names: dict[str, str] = {}
    compute_mode: str = "precomputed"
    density: str = "dense"
    preprocess_policy: str = "cross_section_standard"
    composite_method: str = ""
    data_origin: str = "computed"
    data_start_date: date | None = None
    update_freq: str = "daily"
    compute_engine: str = "plugin"
    report_lag_days: int = 0
    tags: str = ""

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算因子值。

        Args:
            df: 包含 dependencies 列的行情数据 DataFrame

        Returns:
            因子值 DataFrame，列名为 factor_id（组合因子为多个 factor_id）
        """

    def get_definition(self) -> FactorDefinition:
        """获取因子元数据声明。"""
        return FactorDefinition(
            factor_id=self.factor_id,
            display_name=self.display_name,
            category=self.category,
            group_id=self.group_id,
            direction=self.direction,
            usage=self.usage,
            signal_type=self.signal_type,
            base_factor=self.base_factor,
            dependencies=list(self.dependencies),
            min_periods=self.min_periods,
            requires_full_history=self.requires_full_history,
            compute_module=f"{self.__class__.__module__}:{self.__class__.__name__}",
            params=dict(self.params),
            data_origin=self.data_origin,
            data_start_date=self.data_start_date,
            update_freq=self.update_freq,
            compute_engine=self.compute_engine,
            report_lag_days=self.report_lag_days,
            tags=self.tags,
            is_composite=self.is_composite,
            composite_factor_ids=list(self.composite_factor_ids),
            child_display_names=dict(self.child_display_names),
            compute_mode=self.compute_mode,
            density=self.density,
            preprocess_policy=self.preprocess_policy,
            composite_method=self.composite_method,
        )
