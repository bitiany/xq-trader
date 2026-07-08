"""Agent Run SSE 黑盒测试 — 经 Redis 预置事件验证流式接口。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from agent.protocol import EventType, MetaField, RunStatus, run_meta_key
from agent.redis_bus import AgentRedisBus
from xqtrader.domain.agent.utils import new_id

API_PREFIX = "/api/v1/agent"


@pytest.mark.asyncio(loop_scope="session")
async def test_stream_run_events_until_done(api_client) -> None:
    run_id = new_id("run")
    session_id = new_id("sess")
    trace_id = f"trace-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    bus = AgentRedisBus()
    await bus.connect()
    try:
        client = await bus.connect()
        await client.hset(  # type: ignore[misc]
            run_meta_key(run_id),
            mapping={
                MetaField.STATUS.value: RunStatus.RUNNING.value,
                MetaField.SESSION_ID.value: session_id,
                MetaField.TRACE_ID.value: trace_id,
                MetaField.CREATED_AT.value: now,
                MetaField.UPDATED_AT.value: now,
            },
        )
        await bus.publish_event(
            EventType.RUN_START,
            run_id,
            session_id=session_id,
            payload={"message": "test", "trace_id": trace_id},
        )
        await bus.publish_event(
            EventType.TOKEN,
            run_id,
            session_id=session_id,
            payload={"delta": "hello", "trace_id": trace_id},
        )
        await bus.publish_event(
            EventType.MESSAGE,
            run_id,
            session_id=session_id,
            payload={"content": "hello world", "trace_id": trace_id},
        )
        await bus.set_run_status(run_id, RunStatus.COMPLETED)
        await bus.publish_event(
            EventType.DONE,
            run_id,
            session_id=session_id,
            payload={"status": RunStatus.COMPLETED.value, "trace_id": trace_id},
        )

        resp = await api_client.get(f"{API_PREFIX}/runs/{run_id}/stream")
        assert resp.status_code == 200
        body = resp.text
        assert "event: run_start" in body
        assert "event: token" in body
        assert "event: message" in body
        assert "event: done" in body
        assert trace_id in body
        assert "hello" in body
    finally:
        await bus.close()


@pytest.mark.asyncio(loop_scope="session")
async def test_stream_run_not_found(api_client) -> None:
    resp = await api_client.get(f"{API_PREFIX}/runs/run_missing_{uuid.uuid4().hex}/stream")
    assert resp.status_code == 404
