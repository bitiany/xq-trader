"""REST API 集成测试 — 证券接口"""

import pytest

API_PREFIX = "/api/v1"


class TestHealthAPI:

    @pytest.mark.asyncio(loop_scope="session")
    async def test_health_check(self, api_client):
        response = await api_client.get(f"{API_PREFIX}/health")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["status"] == "ok"


class TestSecurityListAPI:

    @pytest.mark.asyncio(loop_scope="session")
    async def test_list_securities_default(self, api_client):
        response = await api_client.get(f"{API_PREFIX}/securities")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["total"] > 0
        assert len(data["data"]["items"]) > 0

    @pytest.mark.asyncio(loop_scope="session")
    async def test_list_securities_with_industry(self, api_client):
        response = await api_client.get(
            f"{API_PREFIX}/securities",
            params={"industry": "银行"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["total"] > 0
        for item in data["data"]["items"]:
            assert item["industry"] == "银行"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_list_securities_pagination(self, api_client):
        response = await api_client.get(
            f"{API_PREFIX}/securities",
            params={"page": 1, "page_size": 2},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]["items"]) <= 2
        assert data["data"]["page"] == 1
        assert data["data"]["page_size"] == 2

    @pytest.mark.asyncio(loop_scope="session")
    async def test_list_securities_invalid_page(self, api_client):
        response = await api_client.get(
            f"{API_PREFIX}/securities",
            params={"page": -1},
        )
        assert response.status_code == 422
        data = response.json()
        assert data["code"] == 422


class TestSecurityDetailAPI:

    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_security_found(self, api_client):
        response = await api_client.get(f"{API_PREFIX}/securities/000001.SZ")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["symbol"] == "000001.SZ"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_security_not_found(self, api_client):
        response = await api_client.get(f"{API_PREFIX}/securities/NOTEXIST.XX")
        assert response.status_code == 404
        data = response.json()
        assert data["code"] == 404
        assert "不存在" in data["message"]


class TestResponseFormat:

    @pytest.mark.asyncio(loop_scope="session")
    async def test_response_has_standard_format(self, api_client):
        response = await api_client.get(f"{API_PREFIX}/securities")
        data = response.json()
        assert "code" in data
        assert "message" in data
        assert "data" in data

    @pytest.mark.asyncio(loop_scope="session")
    async def test_request_id_in_headers(self, api_client):
        response = await api_client.get(f"{API_PREFIX}/health")
        assert "x-request-id" in response.headers
        assert "x-process-time" in response.headers
