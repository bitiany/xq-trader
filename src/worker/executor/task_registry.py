"""任务注册表 — 全局管理任务名称到函数的映射。"""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock
from typing import Any


class TaskRegistry:
    _instance: TaskRegistry | None = None
    _lock: Lock = Lock()

    def __new__(cls) -> TaskRegistry:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self) -> None:
        if not hasattr(self, "_tasks"):
            self._tasks: dict[str, Callable[..., Any]] = {}

    def register(self, task_name: str, func: Callable[..., Any]) -> None:
        self._tasks[task_name] = func

    def get(self, task_name: str) -> Callable[..., Any]:
        if task_name not in self._tasks:
            raise KeyError(f"Task '{task_name}' is not registered")
        return self._tasks[task_name]

    def list_tasks(self) -> list[str]:
        return list(self._tasks.keys())

    def as_dict(self) -> dict[str, Callable[..., Any]]:
        return dict(self._tasks)
