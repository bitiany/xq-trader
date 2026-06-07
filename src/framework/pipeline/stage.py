"""Stage 与 Aspect — 管线处理阶段与切面抽象基类。

开闭原则：
  - Stage：定义数据处理阶段，子类实现 process() 扩展功能
  - Aspect：定义切面钩子，子类实现 before/after/on_error 扩展横切逻辑
  - 引擎不修改，通过组合 Stage 和 Aspect 构建不同管线
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from framework.pipeline.context import PipelineContext
from framework.pipeline.models import StageResult


class Stage(ABC):
    """管线处理阶段基类。

    每个 Stage 负责一个独立的数据处理步骤。
    多个 Stage 串行执行，前一个 Stage 的输出通过 PipelineContext 传递给下一个。

    子类必须实现：
      - name: 阶段名称（用于日志和错误定位）
      - process(item, ctx): 核心处理逻辑

    约定：
      - process() 应通过 ctx.set() 保存中间结果，供后续 Stage 读取
      - process() 返回 StageResult，框架据此判断是否继续执行后续 Stage
      - process() 抛出异常时，框架自动捕获并跳过后续 Stage
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """阶段名称。"""

    @abstractmethod
    async def process(self, item: Any, ctx: PipelineContext) -> StageResult:
        """处理单条数据。

        Args:
            item: 待处理的数据（如标的代码 "000001.SZ"）
            ctx: 管线上下文，可读写中间结果

        Returns:
            StageResult: 处理结果，success=False 时跳过后续 Stage
        """


class Aspect(ABC):
    """管线切面基类 — 在管线执行前后插入横切逻辑。

    典型场景：
      - before: 获取水位日期，设置到 ctx 供 Stage 使用
      - after: 更新水位、记录审计日志
      - on_error: 告警通知、标记失败状态

    多个 Aspect 按注册顺序执行：
      - before: A.before → B.before → stages → B.after → A.after
      - on_error: 所有 Aspect 的 on_error 都会执行（即使某个 on_error 抛异常）
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """切面名称。"""

    async def before(self, item: Any, ctx: PipelineContext) -> None:
        """前切 — 在管线 Stage 执行前调用。

        典型用途：获取水位、初始化上下文、权限检查。
        """

    async def after(self, item: Any, ctx: PipelineContext, result: StageResult) -> None:
        """后切 — 在管线所有 Stage 执行后调用。

        典型用途：更新水位、记录审计日志、清理资源。

        Args:
            item: 处理的数据
            ctx: 管线上下文
            result: 最后一个 Stage 的执行结果
        """

    async def on_error(self, item: Any, ctx: PipelineContext, error: Exception) -> None:
        """错误钩子 — 当管线执行失败时调用。

        典型用途：告警通知、标记失败状态、回滚操作。

        Args:
            item: 处理的数据
            ctx: 管线上下文
            error: 导致失败的异常
        """
