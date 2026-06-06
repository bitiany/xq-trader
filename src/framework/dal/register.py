import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any, cast

from fastapi import FastAPI
from fastapi.routing import _merge_lifespan_context
from sqlalchemy.sql.schema import Table

from framework.dal.base import Base
from framework.dal.enginee import engines_manager
from framework.dal.timescale import TimescaleManager, TimescaleTableConfig

logger = logging.getLogger("DATASOURCE")


class DatasourceManager:
    """数据源管理器，负责初始化和清理数据源"""

    def __init__(
        self,
        app: FastAPI,
        datasource_config: dict[str, Any] | None = None,
        generate_schema: bool = True,
        timescale_config: dict[str, Any] | None = None,
    ) -> None:
        self._initialized = False
        self._app = app
        self._generate_schema = generate_schema
        self._datasource_config = datasource_config or {}
        self._timescale_config = timescale_config or {}

    async def __aenter__(self) -> "DatasourceManager":
        """异步上下文管理器进入方法"""
        await self.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """异步上下文管理器退出方法"""
        await engines_manager.dispose_all()
        logger.info("数据源资源已清理")

    async def initialize(self) -> None:
        """异步初始化数据源"""
        if self._initialized:
            logger.warning("数据源已初始化，跳过")
            return
        engines_manager.initialize(self._datasource_config)
        if self._generate_schema:
            await self.create_tables()
            await self._init_timescale_tables()
        self._initialized = True

    async def create_tables(self) -> None:
        """异步创建数据库表"""
        models_by_datasource = self._collect_models_by_datasource()

        for bind_key, models in models_by_datasource.items():
            if not models:
                continue
            engine = engines_manager.get_engine(bind_key)
            for model in models:
                table = cast(Table, model.__table__)
                async with engine.begin() as conn:
                    await conn.run_sync(lambda sync_conn: table.create(sync_conn, checkfirst=True))
            logger.debug(f"数据源 '{bind_key}' 上成功创建 {len(models)} 个表")

    async def _init_timescale_tables(self) -> None:
        """初始化 TimescaleDB hypertable"""
        timescale_enabled = self._timescale_config.get("enabled", False)
        if not timescale_enabled:
            return

        models_by_datasource = self._collect_models_by_datasource()
        overrides = self._timescale_config.get("overrides", {})

        for bind_key, models in models_by_datasource.items():
            timescale_models = [
                m for m in models if hasattr(m, '__timescale_config__')
            ]
            if not timescale_models:
                continue

            engine = engines_manager.get_engine(bind_key)
            schema = self._get_schema(bind_key)
            manager = TimescaleManager(engine, schema)

            tables_config = {}
            for model in timescale_models:
                config = model.__timescale_config__
                config = self._apply_overrides(model.__tablename__, config, overrides)
                tables_config[model.__tablename__] = config

            results = await manager.initialize_all(tables_config)
            success_count = len(results.get("success", []))
            if success_count > 0:
                logger.info(
                    f"数据源 '{bind_key}' 上成功初始化 {success_count} 个 TimescaleDB 表"
                )
            failed = results.get("failed", [])
            if failed:
                logger.error(f"数据源 '{bind_key}' 上 TimescaleDB 初始化失败的表: {failed}")

    def _apply_overrides(
        self, table_name: str, config: TimescaleTableConfig, overrides: dict[str, Any]
    ) -> TimescaleTableConfig:
        """合并配置文件中的覆盖到装饰器默认值"""
        table_overrides = overrides.get(table_name, {})
        if not table_overrides:
            return config

        merged = TimescaleTableConfig(
            time_column=table_overrides.get("time_column", config.time_column),
            chunk_interval=table_overrides.get("chunk_interval", config.chunk_interval),
            compress_after=table_overrides.get("compress_after", config.compress_after),
            compress_segmentby=table_overrides.get("compress_segmentby", config.compress_segmentby),
        )
        logger.debug(f"表 '{table_name}' TimescaleDB 配置已合并覆盖: {table_overrides}")
        return merged

    def _get_schema(self, bind_key: str) -> str:
        """获取指定数据源的 schema"""
        from framework.dal.enginee import engines_manager
        config = engines_manager.datasource_configs.get(bind_key)
        if config:
            return config.db_schema or "public"
        return "public"

    def _collect_models_by_datasource(self) -> dict[str, list[type[Base]]]:
        """收集所有 ORM 模型并按数据源分组"""
        def get_all_subclasses(cls: type[Base]) -> list[type[Base]]:
            subclasses: list[type[Base]] = []
            for subclass in cls.__subclasses__():
                subclasses.append(subclass)
                subclasses.extend(get_all_subclasses(subclass))
            return subclasses

        models_by_datasource: dict[str, list[type[Base]]] = {}
        added_models: set[type[Base]] = set()
        for subclass in get_all_subclasses(Base):
            if not hasattr(subclass, '__tablename__'):
                continue
            bind_key = getattr(subclass, '__bind_key__', None) or 'default'
            if bind_key not in models_by_datasource:
                models_by_datasource[bind_key] = []
            if subclass not in added_models:
                models_by_datasource[bind_key].append(subclass)
                added_models.add(subclass)
        return models_by_datasource


def register_datasource(
    app: FastAPI,
    datasource_config: dict[str, Any] | None = None,
    generate_schema: bool = True,
    timescale_config: dict[str, Any] | None = None,
) -> None:
    """
    注册数据源到 FastAPI 应用

    使用 FastAPI lifespan 机制，在应用启动时自动初始化数据源，
    在应用关闭时自动清理资源。
    """
    @asynccontextmanager
    async def datasource_lifespan(app_instance: FastAPI) -> AsyncGenerator[None, None]:
        async with DatasourceManager(
            app_instance, datasource_config, generate_schema, timescale_config
        ):
            yield

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _merge_lifespan_context(
        original_lifespan,
        datasource_lifespan
    )

    logger.info("数据源已注册到 FastAPI 应用")


def register_datasource_sync(
    datasource_config: dict[str, Any] | None = None,
    generate_schema: bool = False,
    timescale_config: dict[str, Any] | None = None,
) -> None:
    """
    同步方式注册数据源 — 用于非 FastAPI 进程（如 Celery Worker）。

    初始化引擎管理器，可选创建表结构。
    """
    import asyncio

    engines_manager.initialize(datasource_config or {})
    logger.info("数据源引擎初始化完成（同步模式）")

    if generate_schema:
        manager = DatasourceManager.__new__(DatasourceManager)
        manager._initialized = False
        manager._app = None  # type: ignore[assignment]
        manager._generate_schema = generate_schema
        manager._datasource_config = datasource_config or {}
        manager._timescale_config = timescale_config or {}

        loop = asyncio.get_event_loop()
        loop.run_until_complete(manager.create_tables())
        loop.run_until_complete(manager._init_timescale_tables())
        manager._initialized = True
        logger.info("数据源表结构创建完成（同步模式）")
