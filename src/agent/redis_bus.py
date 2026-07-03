"""Redis 队列与事件流。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from agent.config import agent_settings
from agent.protocol import (
    QUEUE_KEY,
    MetaField,
    RunStatus,
    build_stream_fields,
    run_cancel_key,
    run_events_key,
    run_meta_key,
)
from agent.schemas import AgentEvent, RunTask


class AgentRedisBus:
    def __init__(self, redis_url: str | None = None) -> None:
        self._url = redis_url or agent_settings.REDIS_URL
        self._client: aioredis.Redis | None = None

    async def connect(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(
                self._url,
                decode_responses=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def enqueue_run(self, task: RunTask) -> None:
        client = await self.connect()
        now = datetime.now(timezone.utc).isoformat()
        meta_key = run_meta_key(task.run_id)
        await client.hset(  # type: ignore[misc]
            meta_key,
            mapping={
                MetaField.STATUS.value: RunStatus.QUEUED.value,
                MetaField.SESSION_ID.value: task.session_id,
                MetaField.USER_ID.value: task.user_id,
                MetaField.TENANT_ID.value: task.tenant_id,
                MetaField.TRACE_ID.value: task.trace_id or "",
                MetaField.CREATED_AT.value: now,
                MetaField.UPDATED_AT.value: now,
            },
        )
        await client.rpush(QUEUE_KEY, task.model_dump_json())  # type: ignore[arg-type,misc]

    async def dequeue_run(self, block_seconds: int) -> RunTask | None:
        client = await self.connect()
        result = await client.blpop([QUEUE_KEY], timeout=block_seconds)  # type: ignore[arg-type,misc]
        if not result:
            return None
        _, raw = result
        return RunTask.model_validate_json(raw)

    async def set_run_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        error: str | None = None,
    ) -> None:
        client = await self.connect()
        mapping: dict[str, str] = {
            MetaField.STATUS.value: status.value,
            MetaField.UPDATED_AT.value: datetime.now(timezone.utc).isoformat(),
        }
        if error:
            mapping[MetaField.ERROR.value] = error
        await client.hset(run_meta_key(run_id), mapping=mapping)  # type: ignore[misc]

    async def get_run_meta(self, run_id: str) -> dict[str, str]:
        client = await self.connect()
        return dict(await client.hgetall(run_meta_key(run_id)))  # type: ignore[misc]

    async def is_cancelled(self, run_id: str) -> bool:
        client = await self.connect()
        return bool(await client.exists(run_cancel_key(run_id)))

    async def publish_event(
        self,
        event_type: str,
        run_id: str,
        *,
        session_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> str:
        client = await self.connect()
        fields = build_stream_fields(
            event_type,
            run_id,
            session_id=session_id,
            payload=payload,
        )
        return await client.xadd(run_events_key(run_id), fields)  # type: ignore[arg-type,no-any-return]

    async def read_events(
        self,
        run_id: str,
        last_id: str = "0-0",
        *,
        block_ms: int | None = None,
        count: int = 100,
    ) -> list[tuple[str, AgentEvent]]:
        client = await self.connect()
        kwargs: dict[str, Any] = {
            "count": count,
            "streams": {run_events_key(run_id): last_id},
        }
        if block_ms is not None:
            kwargs["block"] = block_ms
        rows = await client.xread(**kwargs)
        events: list[tuple[str, AgentEvent]] = []
        for _stream, messages in rows:
            for msg_id, fields in messages:
                raw = fields.get("data", "{}")
                events.append((msg_id, AgentEvent.model_validate_json(raw)))
        return events

    async def iter_events(
        self,
        run_id: str,
        *,
        block_ms: int = 5000,
        idle_timeout_s: float = 300.0,
    ) -> AsyncIterator[tuple[str, AgentEvent]]:
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
