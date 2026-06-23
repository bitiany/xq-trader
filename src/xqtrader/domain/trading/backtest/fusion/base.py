"""融合策略基类 — SPI 扩展点"""

from abc import ABC, abstractmethod

from ..core import FusionConfig, RuleResult


class FusionStrategy(ABC):
    """信号融合策略基类

    子类实现 fuse() 方法，将多个 RuleResult 融合为单个 RuleResult。
    融合策略由 FusionConfig.method 指定，由 FusionEngine 路由。
    """

    @abstractmethod
    def fuse(self, results: list[RuleResult], config: FusionConfig) -> RuleResult:
        """融合多个规则结果，返回聚合结果

        Args:
            results: 多个规则的执行结果列表
            config: 融合配置（权重、阈值等）

        Returns:
            融合后的 RuleResult
        """
