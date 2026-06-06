"""调度上下文 — Worker 进程内共享 DAG、屏障触发器、周期管理器、编排步骤映射。"""

from __future__ import annotations

from worker.scheduler.barrier_resolver import BarrierResolver
from worker.scheduler.cycle_manager import CycleManager
from worker.scheduler.dag_builder import DAG

_dag: DAG | None = None
_barrier_resolver: BarrierResolver | None = None
_cycle_manager: CycleManager | None = None
# pipeline_name → list[step_name] 映射
_pipeline_steps: dict[str, list[str]] = {}


def set_context(
    dag: DAG,
    barrier_resolver: BarrierResolver,
    cycle_manager: CycleManager,
    pipeline_steps: dict[str, list[str]] | None = None,
) -> None:
    global _dag, _barrier_resolver, _cycle_manager, _pipeline_steps
    _dag = dag
    _barrier_resolver = barrier_resolver
    _cycle_manager = cycle_manager
    if pipeline_steps is not None:
        _pipeline_steps = pipeline_steps


def get_dag() -> DAG:
    if _dag is None:
        raise RuntimeError("DAG not initialized. Call set_context() first.")
    return _dag


def get_barrier_resolver() -> BarrierResolver:
    if _barrier_resolver is None:
        raise RuntimeError("BarrierResolver not initialized. Call set_context() first.")
    return _barrier_resolver


def get_cycle_manager() -> CycleManager:
    if _cycle_manager is None:
        raise RuntimeError("CycleManager not initialized. Call set_context() first.")
    return _cycle_manager


def get_pipeline_steps() -> dict[str, list[str]]:
    return _pipeline_steps
