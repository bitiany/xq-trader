"""管道数据模型 — 执行结果与错误信息。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StageResult:
    """单个 Stage 的执行结果。"""

    success: bool = True
    data: Any = None
    error: str | None = None

    @staticmethod
    def ok(data: Any = None) -> StageResult:
        return StageResult(success=True, data=data)

    @staticmethod
    def fail(error: str) -> StageResult:
        return StageResult(success=False, error=error)


@dataclass
class ItemError:
    """单条数据处理失败记录。"""

    item: Any
    stage_name: str
    error: str


@dataclass
class PipelineResult:
    """管道引擎执行结果汇总。"""

    pipeline_name: str
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[ItemError] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_name": self.pipeline_name,
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": [{"item": e.item, "stage": e.stage_name, "error": e.error} for e in self.errors],
            "duration_ms": self.duration_ms,
        }
