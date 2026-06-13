"""REST API 集成测试 — 水位接口"""

import pytest

API_PREFIX = "/api/v1"


class TestIncrementalStartDateAPI:
    """GET /api/v1/watermarks/incremental-start"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_watermark_behind_latest(self, api_client):
        """水位落后于最新交易日 → 返回水位日期作为增量起始"""
        response = await api_client.get(
            f"{API_PREFIX}/watermarks/incremental-start",
            params={"data_type": "balance_sheet", "watermark_code": "000001.SZ"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["start_date"] is not None
        assert data["data"]["latest_trade_date"] is not None

    @pytest.mark.asyncio(loop_scope="session")
    async def test_watermark_up_to_date(self, api_client):
        """水位已最新 → 返回 start_date 为 null"""
        response = await api_client.get(
            f"{API_PREFIX}/watermarks/incremental-start",
            params={"data_type": "daily_kline", "watermark_code": "000001.SZ"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["latest_trade_date"] is not None

    @pytest.mark.asyncio(loop_scope="session")
    async def test_watermark_not_found(self, api_client):
        """水位记录不存在 → 视为从未采集，返回最新交易日"""
        response = await api_client.get(
            f"{API_PREFIX}/watermarks/incremental-start",
            params={"data_type": "nonexistent_data_type", "watermark_code": "999999.SZ"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["start_date"] is not None
        assert data["data"]["latest_trade_date"] is not None

    @pytest.mark.asyncio(loop_scope="session")
    async def test_missing_required_params(self, api_client):
        """缺少必填参数 → 422"""
        response = await api_client.get(f"{API_PREFIX}/watermarks/incremental-start")
        assert response.status_code == 422


class TestIncrementalStartDateBatchAPI:
    """GET /api/v1/watermarks/incremental-start/batch"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_batch_with_existing_data_type(self, api_client):
        """批量查询已有数据类型的水位"""
        response = await api_client.get(
            f"{API_PREFIX}/watermarks/incremental-start/batch",
            params={"data_type": "balance_sheet"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["data_type"] == "balance_sheet"
        assert isinstance(data["data"]["items"], dict)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_batch_with_nonexistent_data_type(self, api_client):
        """批量查询不存在的数据类型 → 返回空 items"""
        response = await api_client.get(
            f"{API_PREFIX}/watermarks/incremental-start/batch",
            params={"data_type": "nonexistent_data_type"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["items"] == {}

    @pytest.mark.asyncio(loop_scope="session")
    async def test_batch_missing_required_params(self, api_client):
        """缺少必填参数 → 422"""
        response = await api_client.get(f"{API_PREFIX}/watermarks/incremental-start/batch")
        assert response.status_code == 422
