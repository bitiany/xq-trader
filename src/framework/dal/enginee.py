import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from framework.dal.datasource import DatasourceConfig
from framework.dal.transaction.manager import TransactionManager

logger = logging.getLogger("DATASOURCE.ENGINE")
# ==================== 引擎管理器 ====================
class EnginesManager:
    """
    管理多个数据库引擎 (支持多数据源和读写分离)

    架构职责:
    1. 从 datasource.yml 加载所有数据源配置
    2. 为每个数据源创建独立的引擎和 session 工厂
    3. 提供根据 bind_key 获取对应引擎/Session 的能力
    """
    def __init__(self) -> None:
        self._engines: dict[str, AsyncEngine] = {}
        self._session_makers: dict[str, async_sessionmaker[AsyncSession]] = {}
        self._datasource_configs: dict[str, DatasourceConfig] = {}
        self._initialized: bool = False
        self._active_sessions_var: ContextVar[dict[str, AsyncSession]] = ContextVar(
            'active_sessions', default={}
        )
        # 全局事务管理器实例
        self.transaction_manager = TransactionManager(self)

    def initialize(self, datasources_dict: dict[str, DatasourceConfig] | None = None) -> None:
        """
        初始化所有数据源引擎
        """
        if self._initialized:
            logger.warning("引擎已初始化，跳过")
            return
        try:
            if not datasources_dict:
                raise ValueError("未找到数据源配置，请检查 datasource.yml 或环境变量")

            logger.info(f"***** 开始初始化数据源：{list(datasources_dict)} *****")

            # 遍历所有数据源配置（已经是 DatasourceConfig 对象）
            for bind_key, config in datasources_dict.items():
                self._datasource_configs[bind_key] = config
                self._initialize_datasource(bind_key, config)

            self._initialized = True
            logger.info(f"多数据源初始化完成：{list(datasources_dict.keys())}")

        except Exception as e:
            logger.error(f"数据源初始化失败: {e}", exc_info=True)
            raise RuntimeError(f"数据源初始化失败: {e}") from e

    def is_initialized(self) -> bool:
        return self._initialized

    def _initialize_datasource(self, bind_key: str, config: DatasourceConfig) -> None:
        """
        初始化单个数据源（新方案专用）

        Args:
            bind_key: 数据源标识
            config: DatasourceConfig 对象
        """
        try:
            # 创建引擎
            engine = create_async_engine(
                config.url,
                pool_size=config.pool_size,
                max_overflow=config.max_overflow,
                pool_timeout=config.pool_timeout,
                echo=config.echo,
                echo_pool=False,
                pool_pre_ping=True,
                pool_recycle=3600,
                connect_args={
                    "server_settings": {"client_encoding": "utf8"},
                },
            )

            # 如果配置了非 public schema，添加事件监听器
            if config.db_schema and config.db_schema != 'public':
                @event.listens_for(engine.sync_engine, "connect")
                def set_search_path(dbapi_connection: Any, connection_record: Any) -> None:
                    cursor = dbapi_connection.cursor()
                    cursor.execute(f'SET search_path TO "{config.db_schema}", "public"')
                    cursor.close()
                logger.debug(f"数据源 '{bind_key}' 的 schema '{config.db_schema}' 已设置")

            self._engines[bind_key] = engine
            # 创建 session 工厂
            session_maker = async_sessionmaker(
                bind=engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autocommit=False,
                autoflush=True,
            )
            self._session_makers[bind_key] = session_maker
            logger.debug(f"数据源 '{bind_key}' 初始化成功")

        except Exception as e:
            logger.error(f"初始化数据源 '{bind_key}' 失败：{e}", exc_info=True)
            raise
    def get_engine(self, bind_key: str | None = None) -> AsyncEngine:
        """
        获取指定数据源的引擎

        Args:
            bind_key: 数据源标识，如果为 None 则返回第一个 (默认) 引擎

        Returns:
            SQLAlchemy 异步引擎
        """
        if bind_key is None:
            # 返回第一个引擎作为默认
            if not self._engines:
                raise RuntimeError("没有可用的数据源引擎")
            return next(iter(self._engines.values()))

        if bind_key not in self._engines:
            raise ValueError(f"数据源 '{bind_key}' 未注册")

        return self._engines[bind_key]

    def get_session_maker(self, bind_key: str | None = None) -> async_sessionmaker:
        """
        获取指定数据源的 session 工厂

        Args:
            bind_key: 数据源标识，如果为 None 则返回第一个 (默认) session 工厂

        Returns:
            SQLAlchemy 异步 session 工厂
        """
        if bind_key is None:
            # 返回第一个 session 工厂作为默认
            if not self._session_makers:
                raise RuntimeError("没有可用的 session 工厂")
            return next(iter(self._session_makers.values()))

        if bind_key not in self._session_makers:
            raise ValueError(f"数据源 '{bind_key}' 未注册")

        return self._session_makers[bind_key]
    @asynccontextmanager
    async def get_transaction_session(self, bind_key: str | None = None) -> AsyncGenerator[AsyncSession, None]:
        """
        获取事务感知的 session（上下文管理器）

        核心逻辑：
        1. 检查是否存在活跃事务（通过 TransactionManager）
        2. 如果存在，返回事务的 session（不关闭）
        3. 如果不存在，创建临时 session（退出时自动关闭）

        Args:
            bind_key: 数据源标识

        Yields:
            AsyncSession: 事务感知的 session

        Usage:
            # 在 Base 层使用
            async with cls._get_engines_manager().get_transaction_session(bind_key) as db:
                db.add(instance)
                await db.flush()
                # 不需要 commit，由外层事务控制
                # 如果没有外层事务，session 会自动关闭
        """
        # 尝试获取当前事务的 session
        tx_session = self.transaction_manager.get_current_session()

        if tx_session is not None:
            # 存在活跃事务，直接使用事务的 session
            logger.debug(f"使用事务 session: bind_key={bind_key}")
            yield tx_session
        else:
            # 没有活跃事务，创建临时 session（不加入 active_sessions）
            #logger.debug(f"创建临时 session: bind_key={bind_key}")
            session_maker = self.get_session_maker(bind_key)
            temp_session = session_maker()
            try:
                yield temp_session
                # 临时 session 需要 commit 以持久化数据
                await temp_session.commit()
            except Exception:
                # 发生异常时回滚
                await temp_session.rollback()
                raise
            finally:
                temp_session.expunge_all()
                await temp_session.close()


    async def dispose_all(self) -> None:
        """关闭所有引擎连接"""
        logger.debug("正在关闭所有数据库连接...")
        for engine in self._engines.values():
            await engine.dispose()
        self._engines.clear()
        self._session_makers.clear()
        self._datasource_configs.clear()
        self._initialized = False
        logger.debug("所有数据库连接已关闭")

# 引擎管理器 (全局单例)
engines_manager = EnginesManager()
