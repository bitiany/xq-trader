"""Agent Redis 客户端（API 侧）。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as aioredis

from framework.config.settings import settings
from xqtrader.domain.agent.protocol import (
    QUEUE_KEY,
    MetaField,
    RunStatus,
    run_cancel_key,
    run_events_key,
    run_meta_key,
    session_key,
)
from xqtrader.domain.agent.schemas import AgentEventPayload, RunTask
from xqtrader.domain.agent.utils import utc_now


class AgentRedisBus:
    def __init__(self) -> None:
        self._client: aioredis.Redis | None = None

    async def connect(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(
                settings.REDIS.url,
                decode_responses=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def save_session(
        self,
        session_id: str,
        *,
        session_key_value: str | None,
        title: str | None,
        model: str | None,
        user_id: str,
        tenant_id: str,
    ) -> None:
        client = await self.connect()
        await client.hset(
            session_key(session_id),
            mapping={
                "session_id": session_id,
                "session_key": session_key_value or session_id,
                "title": title or "",
                "model": model or "",
                "user_id": user_id,
                "tenant_id": tenant_id,
                "created_at": utc_now(),
            },
        )  # type: ignore[misc]

    async def get_session(self, session_id: str) -> dict[str, str] | None:
        client = await self.connect()
        data = await client.hgetall(session_key(session_id))  # type: ignore[misc]
        return data or None

    async def enqueue_run(self, task: RunTask) -> None:
        client = await self.connect()
        now = utc_now()
        await client.hset(
            run_meta_key(task.run_id),
            mapping={
                MetaField.STATUS.value: RunStatus.QUEUED.value,
                MetaField.SESSION_ID.value: task.session_id,
                MetaField.USER_ID.value: task.user_id,
                MetaField.TENANT_ID.value: task.tenant_id,
                MetaField.TRACE_ID.value: task.trace_id or "",
                MetaField.CREATED_AT.value: now,
                MetaField.UPDATED_AT.value: now,
            },
        )  # type: ignore[misc]
        await client.rpush(QUEUE_KEY, task.model_dump_json())  # type: ignore[misc]

    async def get_run_meta(self, run_id: str) -> dict[str, str]:
        client = await self.connect()
        return dict(await client.hgetall(run_meta_key(run_id)))  # type: ignore[misc]

    async def request_cancel(self, run_id: str) -> None:
        client = await self.connect()
        await client.set(run_cancel_key(run_id), "1", ex=3600)

    async def read_events(
        self,
        run_id: str,
        last_id: str = "0-0",
        *,
        block_ms: int | None = None,
        count: int = 100,
    ) -> list[tuple[str, AgentEventPayload]]:
        client = await self.connect()
        kwargs: dict[str, Any] = {
            "count": count,
            "streams": {run_events_key(run_id): last_id},
        }
        if block_ms is not None:
            kwargs["block"] = block_ms
        rows = await client.xread(**kwargs)
        events: list[tuple[str, AgentEventPayload]] = []
        for _stream, messages in rows:
            for msg_id, fields in messages:
                raw = fields.get("data", "{}")
                events.append(
                    (msg_id, AgentEventPayload.model_validate_json(raw))
                )
        return events

    async def iter_sse_events(
        self,
        run_id: str,
        *,
        block_ms: int = 5000,
        idle_timeout_s: float = 600.0,
    ) -> AsyncIterator[tuple[str, AgentEventPayload]]:
        last_id = "0-0"
        idle_start = time.monotonic()
        while True:
            batch = await self.read_events(
                run_id,
                last_id,
                block_ms=block_ms,
            )
            if not batch:
                if time.monotonic() - idle_start > idle_timeout_s:
                    break
                await asyncio.sleep(0.05)
                continue
            idle_start = time.monotonic()
            for msg_id, event in batch:
                last_id = msg_id
                yield msg_id, event
                if event.type in ("done", "error"):
                    return
