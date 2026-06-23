"""信号融合子模块 — 多规则/多规则组的信号聚合

提供五种融合策略:
  - AndFusion: 所有规则通过且方向一致才产生信号
  - OrFusion: 任一规则触发即产生信号（buy 优先）
  - WeightedScoreFusion: 加权评分，score × direction 加权求和后与阈值比较
  - WeightedVoteFusion: 加权投票，方向投票加权求和后与阈值比较
  - ICWeightedFusion: IC 加权，用历史 IC 值作为权重加权评分

使用方式:
  engine = FusionEngine()
  result = engine.fuse(rule_results, FusionConfig(method="and"))
"""

from .and_or import AndFusion, OrFusion
from .base import FusionStrategy
from .engine import FusionEngine
from .ic_weighted import ICWeightedFusion
from .weighted import WeightedScoreFusion, WeightedVoteFusion

__all__ = [
    "FusionStrategy",
    "FusionEngine",
    "AndFusion",
    "OrFusion",
    "WeightedScoreFusion",
    "WeightedVoteFusion",
    "ICWeightedFusion",
]
