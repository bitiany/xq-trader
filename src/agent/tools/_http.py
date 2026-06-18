"""Agent 自定义 Tool 共享的 HTTP 客户端。"""

from __future__ import annotations

from typing import Any

import httpx

from agent.config import agent_settings

_TIMEOUT = 60.0

_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=agent_settings.SERVICE_BASE_URL.rstrip("/"),
            timeout=_TIMEOUT,
        )
    return _client


async def api_get(path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    client = await _get_client()
    resp = await client.get(path, params=params)
    resp.raise_for_status()
    body: Any = resp.json()
    if isinstance(body, dict) and "data" in body:
        data: dict[str, Any] = body["data"]
        return data
    if isinstance(body, dict):
        return body
    return {}
