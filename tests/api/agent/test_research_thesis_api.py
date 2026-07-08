"""REST API 集成测试 — 投研论点卡接口"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

API_PREFIX = "/api/v1/research-thesis"


def _thesis_payload(symbol: str, *, valid_until: date) -> dict:
    return {
        "symbol": symbol,
        "as_of": date.today().isoformat(),
        "valid_until": valid_until.isoformat(),
        "direction": "观望",
        "info_gap": {"summary": "测试信息差"},
        "logic_gap": {"summary": "测试逻辑差"},
        "surprise_gap": {"summary": "测试超预期差"},
        "catalysts": {"events": []},
        "core_assumption": "黑盒测试假设",
        "falsification": {"rules": []},
        "tracking_metrics": {"metrics": []},
        "invalidation_rules": {"rules": []},
    }


class TestResearchThesisAPI:

    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_missing_returns_empty(self, api_client) -> None:
        symbol = f"T{uuid.uuid4().hex[:6].upper()}.SZ"
        resp = await api_client.get(f"{API_PREFIX}/{symbol}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == {}

    @pytest.mark.asyncio(loop_scope="session")
    async def test_save_get_and_stale(self, api_client) -> None:
        symbol = f"T{uuid.uuid4().hex[:6].upper()}.SZ"
        valid_until = date.today() + timedelta(days=30)
        save_resp = await api_client.post(
            API_PREFIX,
            json=_thesis_payload(symbol, valid_until=valid_until),
        )
        assert save_resp.status_code == 200
        saved = save_resp.json()
        assert saved["code"] == 0
        assert saved["data"]["symbol"] == symbol
        assert saved["data"]["direction"] == "观望"

        get_resp = await api_client.get(f"{API_PREFIX}/{symbol}")
        assert get_resp.status_code == 200
        fetched = get_resp.json()
        assert fetched["code"] == 0
        assert fetched["data"]["symbol"] == symbol
        assert fetched["data"]["status"] == "active"

        stale_resp = await api_client.post(
            f"{API_PREFIX}/{symbol}/stale",
            json={"reason": "黑盒测试"},
        )
        assert stale_resp.status_code == 200
        stale_body = stale_resp.json()
        assert stale_body["code"] == 0
        assert stale_body["data"]["affected"] >= 1

        after_stale = await api_client.get(f"{API_PREFIX}/{symbol}")
        assert after_stale.status_code == 200
        assert after_stale.json()["data"] == {}

    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_expired_thesis_returns_status(self, api_client) -> None:
        symbol = f"X{uuid.uuid4().hex[:6].upper()}.SZ"
        expired_until = date.today() - timedelta(days=30)
        save_resp = await api_client.post(
            API_PREFIX,
            json=_thesis_payload(symbol, valid_until=expired_until),
        )
        assert save_resp.status_code == 200

        get_resp = await api_client.get(f"{API_PREFIX}/{symbol}")
        assert get_resp.status_code == 200
        data = get_resp.json()["data"]
        assert data["status"] == "expired"
        assert data["symbol"] == symbol
