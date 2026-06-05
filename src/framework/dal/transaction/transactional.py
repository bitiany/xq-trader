"""
事务管理器
提供声明式和编程式事务管理，支持事务传播和多数据源分表场景
"""
from collections.abc import Callable
from functools import wraps
from typing import Any

from framework.dal.transaction.manager import Propagation, TransactionManager


def _get_transaction_manager() -> TransactionManager:
    """延迟导入 TransactionManager，避免循环依赖"""
    from framework.dal.enginee import engines_manager
    return engines_manager.transaction_manager


def transactional(
    propagation: Propagation = Propagation.REQUIRED,
    bind_key: str | None = None
) -> Callable:
    """
    声明式事务装饰器（支持智能数据源路由）

    使用示例：
        # 方式1：显式指定 bind_key
        @transactional(propagation=Propagation.REQUIRED, bind_key='second')
        async def create_order(self, order_data):
            ...

        # 方式2：不指定 bind_key，由 Base 层自动路由
        @transactional()
        async def create_user(self, user_data):
            user = await User.create(**user_data)
            ...

    Args:
        propagation: 事务传播行为
        bind_key: 数据源标识，None 表示由 Base 层根据模型自动路由
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            transaction_manager = _get_transaction_manager()

            if transaction_manager is None:
                raise RuntimeError("TransactionManager 未初始化，请确保 EnginesManager 已初始化")

            async with transaction_manager.transaction(
                propagation=propagation,
                bind_key=bind_key
            ):
                return await func(*args, **kwargs)
        return wrapper
    return decorator
