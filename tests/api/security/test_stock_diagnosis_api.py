"""个股诊股 API 黑盒测试。"""

from __future__ import annotations

import httpx
import pytest

API_PREFIX = "/api/v1"
SYMBOL = "688322.SH"


class TestStockDiagnosisAPI:

    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_stock_diagnosis(self, api_client: httpx.AsyncClient) -> None:
        response = await api_client.get(f"{API_PREFIX}/stocks/{SYMBOL}/diagnosis")
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["symbol"] == SYMBOL
        assert "overall_score" in data
        assert "module_scores" in data
        assert len(data["module_scores"]) == 6
        assert "market_percentile" in data
        assert data["key_metrics"] is not None
        assert data["summary"] is not None
        assert "bullets" in data["summary"]
        assert "cached" in data

    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_stock_diagnosis_cached(self, api_client: httpx.AsyncClient) -> None:
        first = await api_client.get(f"{API_PREFIX}/stocks/{SYMBOL}/diagnosis")
        assert first.status_code == 200
        second = await api_client.get(f"{API_PREFIX}/stocks/{SYMBOL}/diagnosis")
        assert second.status_code == 200
        body = second.json()
        assert body["code"] == 0
        assert body["data"].get("cached") is True

    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_stock_diagnosis_history(self, api_client: httpx.AsyncClient) -> None:
        response = await api_client.get(
            f"{API_PREFIX}/stocks/{SYMBOL}/diagnosis/history",
            params={"days": 30},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["symbol"] == SYMBOL
        assert isinstance(data["items"], list)


class TestStockNewsAPI:

    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_stock_news(self, api_client: httpx.AsyncClient) -> None:
        response = await api_client.get(f"{API_PREFIX}/stocks/{SYMBOL}/news")
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["symbol"] == SYMBOL
        assert "items" in data
        assert "total" in data
        if data["items"]:
            item = data["items"][0]
            assert "id" in item
            assert "published_at" in item
            assert "keywords" in item

    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_stock_announcements(self, api_client: httpx.AsyncClient) -> None:
        response = await api_client.get(f"{API_PREFIX}/stocks/{SYMBOL}/announcements")
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["symbol"] == SYMBOL
        assert isinstance(data["items"], list)
