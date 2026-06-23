"""融合引擎 — 根据 FusionConfig 路由到对应融合策略

FusionEngine 是信号融合的统一入口:
  - 根据 FusionConfig.method 选择融合策略
  - 提供统一的 fuse() 接口，输入 RuleResult 列表，输出融合后的 RuleResult
  - 可在规则组内和组间两个层级使用
"""

import logging

from ..core import FusionConfig, RuleResult
from .and_or import AndFusion, OrFusion
from .base import FusionStrategy
from .ic_weighted import ICWeightedFusion
from .weighted import WeightedScoreFusion, WeightedVoteFusion

logger = logging.getLogger(__name__)


class FusionEngine:
    """融合引擎 — 策略模式路由

    使用方式:
      engine = FusionEngine()
      result = engine.fuse(rule_results, FusionConfig(method="and"))
    """

    _STRATEGIES: dict[str, FusionStrategy] = {
        "and": AndFusion(),
        "or": OrFusion(),
        "weighted_score": WeightedScoreFusion(),
        "weighted_vote": WeightedVoteFusion(),
        "ic_weighted": ICWeightedFusion(),
    }

    def fuse(self, results: list[RuleResult], config: FusionConfig) -> RuleResult:
        """融合多个规则结果

        Args:
            results: 多个规则的执行结果列表
            config: 融合配置

        Returns:
            融合后的 RuleResult
        """
        strategy = self._STRATEGIES.get(config.method)
        if strategy is None:
            raise ValueError(
                f"未知融合方式: {config.method}, 支持: {list(self._STRATEGIES.keys())}"
            )
        return strategy.fuse(results, config)
