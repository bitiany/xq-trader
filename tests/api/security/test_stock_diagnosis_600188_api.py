"""600188.SH 诊股模块数据完整性黑盒测试。"""

from __future__ import annotations

import httpx
import pytest

API_PREFIX = "/api/v1"
SYMBOL = "600188.SH"


def _module_by_key(data: dict, key: str) -> dict:
    for module in data["module_scores"]:
        if module["key"] == key:
            return module
    raise AssertionError(f"module not found: {key}")


class TestStockDiagnosis600188API:

    @pytest.mark.asyncio(loop_scope="session")
    async def test_capital_flow_and_fundamental_have_complete_detail(
        self,
        api_client: httpx.AsyncClient,
    ) -> None:
        await api_client.get(f"{API_PREFIX}/stocks/{SYMBOL}/diagnosis", timeout=180.0)
        response = await api_client.get(
            f"{API_PREFIX}/stocks/{SYMBOL}/diagnosis",
            timeout=30.0,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        data = body["data"]
        assert len(data["module_scores"]) == 6

        capital_flow = _module_by_key(data, "capital_flow")
        assert capital_flow["score"] is not None
        cf_detail = capital_flow["detail"]
        assert cf_detail.get("net_5d") is not None
        assert abs(float(cf_detail["net_5d"])) < 15
        assert len(cf_detail.get("flow_series") or []) >= 10

        fundamental = _module_by_key(data, "fundamental")
        assert fundamental["score"] is not None
        rings = fundamental["detail"].get("rings") or {}
        assert rings.get("growth") is not None
        assert fundamental["detail"].get("highlights", {}).get("roe") is not None

        if data.get("cached"):
            assert data["overall_score"] is not None

    @pytest.mark.asyncio(loop_scope="session")
    async def test_overall_score_matches_module_weights(
        self,
        api_client: httpx.AsyncClient,
    ) -> None:
        response = await api_client.get(
            f"{API_PREFIX}/stocks/{SYMBOL}/diagnosis",
            timeout=120.0,
        )
        assert response.status_code == 200
        data = response.json()["data"]
        scored = [
            (m["score"], m["weight"])
            for m in data["module_scores"]
            if m.get("score") is not None
        ]
        if not scored or data["overall_score"] is None:
            pytest.skip("overall score unavailable")
        total_weight = sum(w for _, w in scored)
        expected = round(sum(s * w for s, w in scored) / total_weight, 1)
        assert data["overall_score"] == expected
