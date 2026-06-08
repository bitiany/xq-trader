"""因子计算管线阶段 — Load → Calc → Persist。

factor_compute 只负责计算原始因子值，不做截面预处理（MAD/Z-score/中性化）。
截面预处理由 factor_evaluate 和 factor_compose 在消费端执行。
"""

from worker.plugins.factor_compute.pipeline.calc_stage import FactorCalcStage
from worker.plugins.factor_compute.pipeline.load_stage import FactorLoadStage
from worker.plugins.factor_compute.pipeline.persist_stage import FactorPersistStage

__all__ = [
    "FactorCalcStage",
    "FactorLoadStage",
    "FactorPersistStage",
]
