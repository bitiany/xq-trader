"""诊股解读与机构持股单元测试。"""

from __future__ import annotations

import httpx
import pytest

from xqtrader.domain.security.services.diagnosis_summary_service import DiagnosisSummaryService

API_PREFIX = "/api/v1"
SYMBOL = "688322.SH"


class TestDiagnosisSummaryService:

    def test_build_context(self) -> None:
        payload = {
            "symbol": SYMBOL,
            "name": "测试",
            "as_of": "2026-07-07",
            "overall_score": 4.4,
            "prev_overall_score": 4.2,
            "module_scores": [
                {"key": "technical", "label": "技术面", "score": 5.0, "prev_score": 4.5},
            ],
            "key_metrics": {"institutional_hold_pct": 27.7},
        }
        context = DiagnosisSummaryService.build_context(payload)
        assert context["symbol"] == SYMBOL
        assert context["overall_score"] == 4.4
        assert len(context["modules"]) == 1
        assert context["key_metrics"]["institutional_hold_pct"] == 27.7


class TestStockDiagnosisPhase3API:

    @pytest.mark.asyncio(loop_scope="session")
    async def test_cached_includes_institutional_hold(self, api_client: httpx.AsyncClient) -> None:
        """缓存路径应返回快照中的基金持股占比（schema v2 快照）。"""
        await api_client.get(f"{API_PREFIX}/stocks/{SYMBOL}/diagnosis", timeout=180.0)
        response = await api_client.get(f"{API_PREFIX}/stocks/{SYMBOL}/diagnosis", timeout=30.0)
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        data = body["data"]
        assert data.get("cached") is True
        metrics = data["key_metrics"]
        assert metrics["institutional_hold_pct"] is not None
        assert metrics["institutional_hold_pct"] > 0
        assert metrics.get("institutional_hold_source") == "fund"
        assert data["summary"]["generated_by"] in {"rule", "agent"}
        assert len(data["summary"]["bullets"]) >= 1
