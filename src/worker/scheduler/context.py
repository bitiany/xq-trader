"""调度上下文 — Worker 进程内共享 DAG、屏障触发器、周期管理器、编排步骤映射。"""

from __future__ import annotations

from framework.commons.exceptions import SchedulerNotInitializedError
from worker.scheduler.barrier_resolver import BarrierResolver
from worker.scheduler.cycle_manager import CycleManager
from worker.scheduler.dag_builder import DAG


class SchedulerContext:
    """进程级调度上下文，封装 DAG、屏障触发器、周期管理器与编排步骤映射。"""

    _dag: DAG | None = None
    _barrier_resolver: BarrierResolver | None = None
    _cycle_manager: CycleManager | None = None
    # pipeline_name → list[step_name] 映射
    _pipeline_steps: dict[str, list[str]] = {}

    @classmethod
    def set_context(
        cls,
        dag: DAG,
        barrier_resolver: BarrierResolver,
        cycle_manager: CycleManager,
        pipeline_steps: dict[str, list[str]] | None = None,
    ) -> None:
        cls._dag = dag
        cls._barrier_resolver = barrier_resolver
        cls._cycle_manager = cycle_manager
        if pipeline_steps is not None:
            cls._pipeline_steps = pipeline_steps

    @classmethod
    def get_dag(cls) -> DAG:
        if cls._dag is None:
            raise SchedulerNotInitializedError("DAG not initialized. Call set_context() first.")
        return cls._dag

    @classmethod
    def get_barrier_resolver(cls) -> BarrierResolver:
        if cls._barrier_resolver is None:
            raise SchedulerNotInitializedError("BarrierResolver not initialized. Call set_context() first.")
        return cls._barrier_resolver

    @classmethod
    def get_cycle_manager(cls) -> CycleManager:
        if cls._cycle_manager is None:
            raise SchedulerNotInitializedError("CycleManager not initialized. Call set_context() first.")
        return cls._cycle_manager

    @classmethod
    def get_pipeline_steps(cls) -> dict[str, list[str]]:
        return cls._pipeline_steps


# ---- 模块级向后兼容函数，委托给 SchedulerContext ----

def set_context(
    dag: DAG,
    barrier_resolver: BarrierResolver,
    cycle_manager: CycleManager,
    pipeline_steps: dict[str, list[str]] | None = None,
) -> None:
    SchedulerContext.set_context(dag, barrier_resolver, cycle_manager, pipeline_steps)


def get_dag() -> DAG:
    return SchedulerContext.get_dag()


def get_barrier_resolver() -> BarrierResolver:
    return SchedulerContext.get_barrier_resolver()


def get_cycle_manager() -> CycleManager:
    return SchedulerContext.get_cycle_manager()


def get_pipeline_steps() -> dict[str, list[str]]:
    return SchedulerContext.get_pipeline_steps()
