"""REST API 集成测试 — Agent 会话接口"""

from __future__ import annotations

import uuid

import pytest

API_PREFIX = "/api/v1/agent"


class TestAgentSessionAPI:

    @pytest.mark.asyncio(loop_scope="session")
    async def test_create_and_get_session(self, api_client) -> None:
        session_key = f"test:agent:{uuid.uuid4().hex[:8]}"
        create_resp = await api_client.post(
            f"{API_PREFIX}/sessions",
            json={"session_key": session_key, "title": "黑盒测试"},
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        assert created["code"] == 0
        session_id = created["data"]["session_id"]
        assert created["data"]["session_key"] == session_key

        get_resp = await api_client.get(f"{API_PREFIX}/sessions/{session_id}")
        assert get_resp.status_code == 200
        fetched = get_resp.json()
        assert fetched["code"] == 0
        assert fetched["data"]["session_id"] == session_id

    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_history_empty(self, api_client) -> None:
        session_key = f"test:history:{uuid.uuid4().hex[:8]}"
        resp = await api_client.get(
            f"{API_PREFIX}/history",
            params={"session_key": session_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["messages"] == []

    @pytest.mark.asyncio(loop_scope="session")
    async def test_submit_message_accepted(self, api_client) -> None:
        create_resp = await api_client.post(
            f"{API_PREFIX}/sessions",
            json={"session_key": f"test:msg:{uuid.uuid4().hex[:8]}"},
        )
        assert create_resp.status_code == 201
        session_id = create_resp.json()["data"]["session_id"]

        msg_resp = await api_client.post(
            f"{API_PREFIX}/sessions/{session_id}/messages",
            json={"content": "ping"},
        )
        assert msg_resp.status_code == 202
        body = msg_resp.json()
        assert body["code"] == 0
        assert body["data"]["run_id"]
        assert body["data"]["status"] == "queued"
