"""任务包装器 — CronTaskWrapper 包装定时任务，注入 cycle_id 并通知屏障触发器。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class BarrierResolverProtocol(Protocol):
    def on_task_completed(self, task_name: str, cycle_id: str, status: str) -> None: ...


@runtime_checkable
class CycleManagerProtocol(Protocol):
    @property
    def cycle_id(self) -> str: ...


class CronTaskWrapper:
    def __init__(
        self,
        task_name: str,
        business_func: Callable[..., Any],
        barrier_resolver: BarrierResolverProtocol,
        cycle_manager: CycleManagerProtocol,
    ) -> None:
        self._task_name = task_name
        self._business_func = business_func
        self._barrier_resolver = barrier_resolver
        self._cycle_manager = cycle_manager

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        cycle_id = self._cycle_manager.cycle_id
        kwargs["cycle_id"] = cycle_id
        try:
            result = self._business_func(*args, **kwargs)
            self._barrier_resolver.on_task_completed(self._task_name, cycle_id, "SUCCESS")
            return result
        except Exception:
            self._barrier_resolver.on_task_completed(self._task_name, cycle_id, "FAILED")
            raise
