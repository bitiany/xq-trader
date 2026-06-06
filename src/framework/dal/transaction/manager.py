"""
事务管理器
提供声明式和编程式事务管理，支持事务传播和多数据源分表场景
"""
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from enum import Enum
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("TRANSACTION")


class Propagation(Enum):
    """事务传播行为"""
    REQUIRED = "REQUIRED"  # 如果存在事务则加入，否则新建（默认）
    REQUIRES_NEW = "REQUIRES_NEW"  # 总是新建事务，挂起当前事务
    MANDATORY = "MANDATORY"  # 必须存在事务，否则异常
    NOT_SUPPORTED = "NOT_SUPPORTED"  # 不支持事务，以非事务方式执行
    NEVER = "NEVER"  # 必须在非事务环境下执行


# 当前事务上下文
_current_transaction: ContextVar[Optional['TransactionContext']] = ContextVar(
    '_current_transaction', default=None
)


class TransactionContext:
    """事务上下文，用于跟踪当前事务状态"""

    def __init__(self, session: AsyncSession, propagation: Propagation, bind_key: str | None = None):
        self.session = session
        self.propagation = propagation
        self.bind_key = bind_key  # 记录数据源标识
        self.nested = False  # 是否是嵌套事务
        self._committed = False
        self._rolled_back = False

    async def commit(self) -> None:
        """提交事务"""
        if not self._committed and not self._rolled_back:
            await self.session.commit()
            self._committed = True
            logger.debug(f"事务已提交：{id(self.session)}")

    async def rollback(self) -> None:
        """回滚事务"""
        if not self._committed and not self._rolled_back:
            await self.session.rollback()
            self._rolled_back = True
            logger.debug(f"事务已回滚：{id(self.session)}")

    async def close(self) -> None:
        """关闭 session"""
        await self.session.close()


class TransactionManager:
    """
    事务管理器

    使用示例：

    1. 声明式事务（推荐）：
        @transactional(propagation=Propagation.REQUIRED)
        async def create_order(self, order_data):
            ...

    2. 编程式事务：
        async with transaction_manager.transaction():
            # 业务逻辑
            await transaction_manager.commit()
    """
    def __init__(self, engines_manager: Any):
        self._context = _current_transaction
        self.engines_manager = engines_manager

    def get_current_session(self) -> AsyncSession | None:
        """获取当前事务的 session"""
        ctx = self._context.get()
        return ctx.session if ctx else None

    def has_active_transaction(self) -> bool:
        """检查是否存在活跃事务"""
        ctx = self._context.get()
        return ctx is not None and not ctx._committed and not ctx._rolled_back

    @asynccontextmanager
    async def transaction(
        self,
        propagation: Propagation = Propagation.REQUIRED,
        bind_key: str | None = None,
        model_class: type | None = None,
    ) -> AsyncGenerator[TransactionContext, None]:
        """
        创建事务上下文（支持智能数据源路由）

        Args:
            propagation: 事务传播行为
            bind_key: 数据源标识，优先级高于 model_class
            model_class: ORM 模型类，从中提取 __bind_key__（如果 bind_key 为 None）

        Yields:
            TransactionContext

        Usage:
            # 方式1：显式指定 bind_key
            async with transaction_manager.transaction(bind_key='second'):
                ...

            # 方式2：从模型类自动提取 bind_key
            async with transaction_manager.transaction(model_class=User):
                ...

            # 方式3：使用装饰器（推荐）
            @transactional(propagation=Propagation.REQUIRED, bind_key='second')
            async def create_order():
                ...
        """
        current_ctx = self._context.get()

        # 智能路由：如果未指定 bind_key，尝试从 model_class 提取
        if bind_key is None and model_class is not None:
            bind_key = getattr(model_class, '__bind_key__', None) or 'default'
            logger.debug(f"从模型 {model_class.__name__} 提取 bind_key: {bind_key}")

        # 根据传播行为决定如何处理
        if propagation == Propagation.REQUIRED:
            if current_ctx and not current_ctx._committed and not current_ctx._rolled_back:
                # 加入现有事务
                logger.debug("加入现有事务")
                yield current_ctx
                return
            # 否则创建新事务

        elif propagation == Propagation.REQUIRES_NEW:
            pass  # 始终创建新事务

        elif propagation == Propagation.MANDATORY:
            if not current_ctx or current_ctx._committed or current_ctx._rolled_back:
                raise RuntimeError(
                    "Mandatory transaction required but none exists")

        elif propagation == Propagation.NOT_SUPPORTED:
            if current_ctx:
                # 以非事务方式执行
                logger.debug("以非事务方式执行")
                yield current_ctx
                return

        elif propagation == Propagation.NEVER:
            if current_ctx and not current_ctx._committed and not current_ctx._rolled_back:
                raise RuntimeError(
                    "Transaction exists but execution must be non-transactional")

        # 创建新的事务
        logger.debug(
            f"创建新事务，propagation={propagation.value}, bind_key={bind_key}")
        # 根据 bind_key 获取对应的 session
        session_maker = self.engines_manager.get_session_maker(bind_key if bind_key else 'default')
        session = session_maker()
        # 标记 session 的 bind_key，用于 Repository 层检查
        setattr(session, '_bind_key', bind_key or 'default')  # type: ignore

        ctx = TransactionContext(session, propagation, bind_key)

        # 保存旧上下文用于恢复
        old_ctx = self._context.get()
        old_token = None

        try:
            # 根据传播行为决定上下文管理
            if propagation == Propagation.REQUIRES_NEW:
                # 挂起当前事务，创建新事务
                if old_ctx is not None:
                    logger.debug("挂起当前事务，创建新事务")
                old_token = self._context.set(ctx)
            elif propagation == Propagation.REQUIRED:
                if old_ctx is not None and not old_ctx._committed and not old_ctx._rolled_back:
                    # 复用现有事务
                    logger.debug("加入现有事务")
                    yield old_ctx
                    return
                # 设置新事务上下文
                old_token = self._context.set(ctx)

            yield ctx

            # 如果没有显式提交或回滚，则自动提交
            if not ctx._committed and not ctx._rolled_back:
                logger.debug(f"事务自动提交：{id(ctx.session)}")
                await ctx.commit()
        except Exception as e:
            # 发生异常自动回滚
            logger.debug(f"事务自动回滚：{id(ctx.session)}, error={e}")
            await ctx.rollback()
            raise
        finally:
            # 恢复旧上下文
            if old_token is not None:
                self._context.reset(old_token)
            # 只关闭当前事务的 session，不影响外部事务
            await ctx.close()

    async def commit(self) -> None:
        """提交当前事务"""
        ctx = self._context.get()
        if ctx and not ctx._committed and not ctx._rolled_back:
            await ctx.commit()

    async def rollback(self) -> None:
        """回滚当前事务"""
        ctx = self._context.get()
        if ctx and not ctx._committed and not ctx._rolled_back:
            await ctx.rollback()




