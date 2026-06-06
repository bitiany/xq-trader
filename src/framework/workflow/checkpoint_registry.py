"""LangGraph Checkpoint 持久化管理器。

使用 langgraph-checkpoint-postgres 的同步 PostgresSaver，
将工作流状态持久化到 PostgreSQL 的 research schema 中。

设计要点：
  - CheckpointManager 封装所有 checkpoint 生命周期管理
  - 每个 flow_id 共享同一个 checkpointer 实例（内部按 thread_id 隔离）
  - 首次调用时自动执行 setup() 建表
  - 使用 research 数据库连接（与业务数据同库，便于关联查询）
  - 进程重启后工作流状态不丢失，支持 interrupt/resume 跨重启恢复
  - 使用同步 psycopg 连接 + asyncio.to_thread 异步适配
    （避免 Windows 上 AsyncPostgresSaver 的 ProactorEventLoop 兼容问题）
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

import psycopg
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from psycopg.rows import dict_row

if TYPE_CHECKING:
    from langgraph.checkpoint.postgres import PostgresSaver

logger = logging.getLogger("WORKFLOW.CHECKPOINT")


class AsyncPostgresSaverAdapter(BaseCheckpointSaver):
    """异步适配器：将同步 PostgresSaver 包装为异步接口。

    使用 asyncio.to_thread() 在线程池中执行同步 psycopg 操作，
    避免 Windows 上 psycopg 异步模式的 ProactorEventLoop 兼容问题。
    """

    def __init__(self, sync_saver: PostgresSaver) -> None:
        super().__init__()
        self._sync = sync_saver
        self.serde = sync_saver.serde

    def setup(self) -> None:
        self._sync.setup()

    # ---- 同步方法直接委托 ----

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return self._sync.get_tuple(config)  # type: ignore[no-any-return]

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        return self._sync.list(config, filter=filter, before=before, limit=limit)  # type: ignore[no-any-return]

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return self._sync.put(config, checkpoint, metadata, new_versions)  # type: ignore[no-any-return]

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        self._sync.put_writes(config, writes, task_id, task_path=task_path)

    # ---- 异步方法通过 to_thread 委托 ----

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return await asyncio.to_thread(self._sync.get_tuple, config)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """异步迭代 checkpoint 列表。

        将同步迭代器的每个元素通过 to_thread 获取，
        避免在事件循环中阻塞。
        """
        items = await asyncio.to_thread(
            list,
            self._sync.list(config, filter=filter, before=before, limit=limit)
        )
        for item in items:
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return await asyncio.to_thread(
            self._sync.put, config, checkpoint, metadata, new_versions
        )

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        return await asyncio.to_thread(
            self._sync.put_writes, config, writes, task_id, task_path=task_path
        )


class CheckpointManager:
    """Checkpoint 生命周期管理器。

    封装数据库连接、PostgresSaver 实例和适配器的创建与清理，
    对外提供 get_checkpointer() 接口，隐藏内部实现细节。
    """

    def __init__(self) -> None:
        self._adapter: AsyncPostgresSaverAdapter | None = None
        self._sync_saver: PostgresSaver | None = None
        self._conn: psycopg.Connection | None = None
        self._setup_done: bool = False

    def _build_research_dsn(self) -> str:
        """从项目 datasource 配置构建 research 数据库的 DSN。"""
        from framework.dal.enginee import engines_manager

        if not engines_manager.is_initialized():
            raise RuntimeError("数据源引擎未初始化，无法创建 LangGraph checkpointer")

        ds_config = engines_manager.datasource_configs.get("research")
        if ds_config is None:
            raise RuntimeError("未找到 research 数据源配置")

        url = ds_config.url

        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        dbname = parsed.path.lstrip("/")
        user = parsed.username or ""
        password = unquote(parsed.password or "")

        return f"host={host} port={port} dbname={dbname} user={user} password={password}"

    @property
    def datasource_configs(self) -> Any:
        """提供对数据源配置的只读访问（替代直接访问私有属性）。"""
        from framework.dal.enginee import engines_manager
        return engines_manager.datasource_configs

    def get_checkpointer(self, flow_id: str) -> AsyncPostgresSaverAdapter:
        """获取 LangGraph Checkpointer 异步适配器实例。"""
        if self._adapter is not None and self._setup_done:
            return self._adapter

        from langgraph.checkpoint.postgres import PostgresSaver

        dsn = self._build_research_dsn()
        logger.info("初始化 LangGraph PostgresSaver (research DB, sync+async adapter)")

        self._conn = psycopg.connect(
            dsn,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,  # type: ignore[arg-type]
        )

        self._sync_saver = PostgresSaver(conn=self._conn)  # type: ignore[arg-type]

        if not self._setup_done:
            self._sync_saver.setup()
            self._setup_done = True
            logger.info("LangGraph checkpoint 表已创建")

        self._adapter = AsyncPostgresSaverAdapter(self._sync_saver)

        return self._adapter

    def cleanup(self) -> None:
        """清理连接（应用关闭时调用）。"""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception as e:
                logger.warning(f"Failed to close checkpoint connection: {e}")
        self._adapter = None
        self._sync_saver = None
        self._conn = None
        self._setup_done = False


# 全局单例
_checkpoint_manager = CheckpointManager()


def get_checkpointer(flow_id: str) -> AsyncPostgresSaverAdapter:
    """获取 LangGraph Checkpointer（兼容旧接口）。"""
    return _checkpoint_manager.get_checkpointer(flow_id)


def cleanup_checkpointer() -> None:
    """清理 checkpointer 连接（兼容旧接口）。"""
    _checkpoint_manager.cleanup()
