"""回测 API 集成测试 — 请求验证 + 黑盒接口测试。"""

import pytest

API_PREFIX = "/api/v1"


class TestBacktestRunValidation:
    """POST /api/v1/backtest/run — 请求验证。"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_missing_required_fields(self, api_client) -> None:
        """缺少必填字段 → 422"""
        response = await api_client.post(f"{API_PREFIX}/backtest/run", json={})
        assert response.status_code == 422

    @pytest.mark.asyncio(loop_scope="session")
    async def test_invalid_date_range(self, api_client) -> None:
        """start_date >= end_date → 400 业务异常"""
        response = await api_client.post(
            f"{API_PREFIX}/backtest/run",
            json={
                "strategy_id": "test_001",
                "symbols": ["000001.SZ"],
                "start_date": "2024-06-01",
                "end_date": "2024-01-01",
            },
        )
        assert response.status_code == 400
        data = response.json()
        assert "start_date" in data["message"]

    @pytest.mark.asyncio(loop_scope="session")
    async def test_empty_symbols(self, api_client) -> None:
        """symbols 为空 → 400 业务异常"""
        response = await api_client.post(
            f"{API_PREFIX}/backtest/run",
            json={
                "strategy_id": "test_001",
                "symbols": [],
                "start_date": "2024-01-01",
                "end_date": "2024-06-01",
            },
        )
        assert response.status_code == 400
        data = response.json()
        assert "symbols" in data["message"]

    @pytest.mark.asyncio(loop_scope="session")
    async def test_valid_request_format(self, api_client) -> None:
        """合法请求格式 → 不返回 422（可能 400/500 因策略不存在，但不是 422）"""
        response = await api_client.post(
            f"{API_PREFIX}/backtest/run",
            json={
                "strategy_id": "nonexistent_strategy",
                "symbols": ["000001.SZ"],
                "start_date": "2024-01-01",
                "end_date": "2024-06-01",
                "initial_capital": 1000000,
                "commission_rate": 0.0003,
                "slippage": 0.001,
                "indicator_specs": [
                    {"name": "atr", "params": {"period": 14}},
                ],
                "lookback_days": 60,
                "generate_report": False,
                "rf": 0.0,
            },
        )
        # 策略不存在应返回 400 或 500，但不应是 422（格式验证通过）
        assert response.status_code != 422
