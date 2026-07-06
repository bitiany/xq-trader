"""nanobot 会话记忆的 PostgreSQL 后端。

鸭子兼容 nanobot 的 SessionManager，替换其默认 jsonl 文件存储，使框架原生的
「按 session_key 自动加载历史 → 注入上下文 → 每轮自动落盘」直接持久化到 PostgreSQL。

框架以**同步**方式调用（get_or_create / save / ...），而 xqtrader DAL 是异步。
本类持有一个后台线程运行独立 event loop，同步方法通过 run_coroutine_threadsafe
桥接到异步 DAL；数据源引擎在该独立 loop 上初始化并使用，避免跨事件循环的
asyncpg 连接池绑定问题。
"""

from __future__ import annotations

import asyncio
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from nanobot.session.manager import Session
from nanobot.utils.helpers import safe_filename

from framework.commons.logger import get_logger
from framework.config.settings import settings
from framework.dal.datasource_loader import DatasourceLoader
from framework.dal.enginee import engines_manager
from framework.dal.transaction.manager import Propagation
from framework.dal.transaction.transactional import transactional
from xqtrader.domain.agent.models.session import AgentMessage, AgentSession

logger = get_logger("AGENT_SESSION_PG")


class PgSessionManager:
    """PostgreSQL 会话后端 — 鸭子兼容 nanobot SessionManager。"""

    _CACHE_MAX = 64

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.sessions_dir = workspace / "sessions"  # 兼容属性，不实际写文件
        self._cache: OrderedDict[str, Session] = OrderedDict()

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="pg-session-loop", daemon=True,
        )
        self._thread.start()
        self._submit(self._init_datasource())
        logger.info("PgSessionManager initialized (workspace=%s)", workspace)

    # ==================== 事件循环桥接 ====================

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro: Any) -> Any:
        """在后台 loop 上同步执行协程并返回结果。"""
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def run_coroutine(self, coro: Any) -> Any:
        """对外暴露的协程桥接入口（短期记忆等跨模块 DB 查询复用）。"""
        return self._submit(coro)

    @staticmethod
    async def _init_datasource() -> None:
        if not engines_manager.is_initialized():
            loader = DatasourceLoader(settings.APP.DB_CONFIG_PATH)
            engines_manager.initialize(loader.datasources)
            logger.info("Datasource initialized on pg-session-loop")

    # ==================== nanobot SessionManager 接口 ====================

    @staticmethod
    def safe_key(key: str) -> str:
        return str(safe_filename(key.replace(":", "_")))

    def get_or_create(self, key: str) -> Session:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        session = self._submit(self._load(key)) or Session(key=key)
        self._cache[key] = session
        self._evict_if_needed()
        return session

    def save(self, session: Session, *, fsync: bool = False) -> None:
        self._submit(self._persist(session))
        self._cache[session.key] = session
        self._cache.move_to_end(session.key)
        self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        while len(self._cache) > self._CACHE_MAX:
            self._cache.popitem(last=False)

    def invalidate(self, key: str) -> None:
        self._cache.pop(key, None)

    def delete_session(self, key: str) -> bool:
        self.invalidate(key)
        return bool(self._submit(self._delete(key)))

    def list_sessions(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self._submit(self._list()))

    def read_session_file(self, key: str) -> dict[str, Any] | None:
        session = self._submit(self._load(key))
        if session is None:
            return None
        return self._to_payload(session)

    def flush_all(self) -> int:
        # save() 已即时落盘，缓存始终持久化，无需额外刷盘。
        return len(self._cache)

    # ==================== 异步 DB 实现 ====================

    @staticmethod
    async def _load(key: str) -> Session | None:
        meta_row = await AgentSession.get_or_none(session_key=key)
        if meta_row is None:
            return None
        rows = await AgentMessage.filter(
            session_key=key, order_by=AgentMessage.seq,
        )
        return Session(
            key=key,
            messages=[r.payload for r in rows],
            created_at=meta_row.created_at or datetime.now(timezone.utc),  # type: ignore[arg-type]
            updated_at=meta_row.updated_at or datetime.now(timezone.utc),  # type: ignore[arg-type]
            metadata=meta_row.meta or {},
            last_consolidated=meta_row.last_consolidated,
        )

    @staticmethod
    @transactional(propagation=Propagation.REQUIRED, bind_key="default")
    async def _persist(session: Session) -> None:
        """全量重写会话（对齐 nanobot jsonl 原子重写语义）。"""
        exists = await AgentSession.get_or_none(session_key=session.key)
        meta_data = {
            "meta": session.metadata or None,
            "last_consolidated": session.last_consolidated,
            "updated_at": session.updated_at,
        }
        if exists:
            await AgentSession.update_by(meta_data, session_key=session.key)
        else:
            await AgentSession.create(
                session_key=session.key,
                created_at=session.created_at,
                **meta_data,
            )
        await AgentMessage.delete_many(session_key=session.key)
        for i, msg in enumerate(session.messages):
            await AgentMessage.create(session_key=session.key, seq=i, payload=msg)

    @staticmethod
    async def _delete(key: str) -> int:
        await AgentMessage.delete_many(session_key=key)
        return await AgentSession.delete_many(session_key=key)

    @classmethod
    async def _list(cls) -> list[dict[str, Any]]:
        rows = await AgentSession.filter(order_by=AgentSession.updated_at.desc())
        return [
            {
                "key": r.session_key,
                "created_at": r.created_at.isoformat() if r.created_at else None,  # type: ignore[attr-defined]
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,  # type: ignore[attr-defined]
                "title": (r.meta or {}).get("title", ""),
                "preview": "",
                "path": "",
            }
            for r in rows
        ]

    @staticmethod
    def _to_payload(session: Session) -> dict[str, Any]:
        return {
            "key": session.key,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "metadata": session.metadata,
            "messages": session.messages,
        }
