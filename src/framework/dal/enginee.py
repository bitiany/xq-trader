import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import ORMExecuteState
from sqlalchemy.sql.expression import UpdateBase

from framework.commons.exceptions import DatasourceConfigNotFoundError, DatasourceNotInitializedError
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
                raise DatasourceConfigNotFoundError("未找到数据源配置，请检查 datasource.yml 或环境变量")

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

    @property
    def datasource_configs(self) -> dict[str, DatasourceConfig]:
        """数据源配置的只读访问。"""
        return self._datasource_configs

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
                    "server_settings": {
                        "client_encoding": "utf8",
                        "timezone": "Asia/Shanghai",
                    },
                },
            )

            # 如果配置了非 public schema，添加事件监听器
            if config.db_schema and config.db_schema != 'public':
                @event.listens_for(engine.sync_engine, "connect")
                def set_search_path(dbapi_connection: Any, connection_record: Any) -> None:
                    cursor = dbapi_connection.cursor()
                    cursor.execute(f'SET search_path TO "{config.db_schema}", "public"')
                    cursor.execute("SET timezone TO 'Asia/Shanghai'")
                    cursor.close()
                logger.debug(f"数据源 '{bind_key}' 的 schema '{config.db_schema}' 已设置")
            else:
                @event.listens_for(engine.sync_engine, "connect")
                def set_timezone(dbapi_connection: Any, connection_record: Any) -> None:
                    cursor = dbapi_connection.cursor()
                    cursor.execute("SET timezone TO 'Asia/Shanghai'")
                    cursor.close()

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
                raise DatasourceNotInitializedError("没有可用的数据源引擎")
            return next(iter(self._engines.values()))

        if bind_key not in self._engines:
            raise DatasourceConfigNotFoundError(f"数据源 '{bind_key}' 未注册")

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
                raise DatasourceNotInitializedError("没有可用的 session 工厂")
            return next(iter(self._session_makers.values()))

        if bind_key not in self._session_makers:
            raise DatasourceConfigNotFoundError(f"数据源 '{bind_key}' 未注册")

        return self._session_makers[bind_key]
    @asynccontextmanager
    async def get_transaction_session(self, bind_key: str | None = None) -> AsyncGenerator[AsyncSession, None]:
        """
        获取事务感知的 session（上下文管理器）

        核心逻辑：
        1. 检查是否存在活跃事务（通过 TransactionManager）
        2. 若存在且 bind_key 匹配，返回事务的 session（不关闭）
        3. 若不存在或 bind_key 不匹配，创建临时 session（退出时自动关闭）

        bind_key 不匹配场景：跨 schema 只读查询（如 trading 事务内查询 stock CandlestickDaily）。
        此时使用独立临时 session，保证查询能命中正确的 schema search_path。

        跨 schema 写保护：当外层活跃事务存在且 bind_key 不匹配时，临时 session 强制只读，
        防止调用方误用导致跨 schema 数据不一致（外层事务回滚无法回滚临时 session 的独立 commit）。
        如需跨 schema 写操作，必须显式使用 @transactional(bind_key='...') 拆分到独立事务。

        Args:
            bind_key: 数据源标识

        Yields:
            AsyncSession: 事务感知的 session
        """
        tx_session = self.transaction_manager.get_current_session()
        requested_bind_key = bind_key or 'default'
        in_active_tx = tx_session is not None

        if tx_session is not None:
            tx_bind_key = getattr(tx_session, '_bind_key', None)
            if tx_bind_key == requested_bind_key:
                # bind_key 匹配，使用事务 session（保证事务一致性）
                yield tx_session
                return
            # bind_key 不匹配：跨 schema 临时 session 不在事务内，
            # 外层事务回滚无法回滚其独立 commit，故强制只读防止数据不一致。
            logger.debug(
                f"bind_key 不匹配 (tx={tx_bind_key}, requested={requested_bind_key})，"
                f"创建只读独立 session"
            )

        # 没有活跃事务 或 bind_key 不匹配：创建临时 session
        session_maker = self.get_session_maker(bind_key)
        temp_session = session_maker()
        setattr(temp_session, '_bind_key', requested_bind_key)  # type: ignore

        # 跨 schema 写保护（双层覆盖）：
        # 1. do_orm_execute 事件：拦截所有 db.execute(update/delete/insert) 等 Core 级 SQL 写
        #    （Core 级 SQL 不污染 session.new/dirty/deleted，必须用事件机制才能拦截）
        # 2. new/dirty/deleted 检查：拦截 ORM 级 db.add(self) 写
        # 外层活跃事务存在时强制只读，避免外层事务回滚无法回滚临时 session 的独立 commit
        def _enforce_read_only(execute_state: ORMExecuteState) -> None:
            if isinstance(execute_state.statement, UpdateBase):
                raise RuntimeError(
                    f"跨 schema 写操作不允许在活跃事务内的临时 session 中执行 "
                    f"(requested_bind_key={requested_bind_key})，"
                    f"请使用 @transactional(bind_key='{requested_bind_key}') 拆分到独立事务"
                )

        if in_active_tx:
            event.listen(temp_session.sync_session, "do_orm_execute", _enforce_read_only)

        try:
            yield temp_session
            # 提交前校验只读约束：拦截 ORM 级 db.add(self) 写（Core 级 SQL 已被事件拦截）
            if in_active_tx and (temp_session.new or temp_session.dirty or temp_session.deleted):
                raise RuntimeError(
                    f"跨 schema 写操作不允许在活跃事务内的临时 session 中执行 "
                    f"(requested_bind_key={requested_bind_key})，"
                    f"请使用 @transactional(bind_key='{requested_bind_key}') 拆分到独立事务"
                )
            # 临时 session 需要 commit 以持久化数据
            await temp_session.commit()
        except Exception:
            # 发生异常时回滚
            await temp_session.rollback()
            raise
        finally:
            if in_active_tx:
                event.remove(temp_session.sync_session, "do_orm_execute", _enforce_read_only)
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
