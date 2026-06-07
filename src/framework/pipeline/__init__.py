"""管道引擎 — 通用并发管线处理框架。

设计原则：
  - 开闭原则：通过 Stage/Aspect 子类扩展，不修改引擎代码
  - 数据并行：每个 item 独立走完所有 stage，item 之间互不依赖
  - 并发控制：asyncio.Semaphore 控制最大并发数
  - 切面编程：Aspect 基类支持 before/after/on_error 钩子
  - 上下文传递：PipelineContext per item，线程安全

典型场景：
  A股全市场数据采集 — 5500+ 标的逐个走 download → transform → persist 管线
"""

from framework.pipeline.context import PipelineContext
from framework.pipeline.engine import Pipeline, PipelineEngine
from framework.pipeline.errors import PipelineError, PipelineStageError
from framework.pipeline.models import ItemError, PipelineResult, StageResult
from framework.pipeline.stage import Aspect, Stage

__all__ = [
    "Aspect",
    "ItemError",
    "Pipeline",
    "PipelineContext",
    "PipelineEngine",
    "PipelineError",
    "PipelineResult",
    "PipelineStageError",
    "Stage",
    "StageResult",
]
