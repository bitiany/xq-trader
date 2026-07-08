"""诊股 Phase 4 契约与规则解读单元测试。"""

from __future__ import annotations

import httpx
import pytest

from xqtrader.domain.security.services.stock_diagnosis_service import StockDiagnosisService

API_PREFIX = "/api/v1"
SYMBOL = "688322.SH"


class TestDiagnosisRuleSummary:

    def test_build_rule_summary_narrative_with_highlights(self) -> None:
        modules = [
            {
                "key": "sentiment",
                "label": "消息面",
                "score": 3.0,
                "prev_score": 5.0,
                "weight": 0.15,
                "detail": {},
            },
            {
                "key": "technical",
                "label": "技术面",
                "score": 4.0,
                "prev_score": 6.0,
                "weight": 0.20,
                "detail": {},
            },
        ]

        class _Prev:
            overall_score = 5.0

        summary = StockDiagnosisService._build_rule_summary(
            modules,
            4.4,
            _Prev(),  # type: ignore[arg-type]
            name="测试股份",
            prev_as_of="2026-07-05",
        )

        assert "narrative" in summary
        assert "【消息面】" in summary["narrative"]
        assert summary.get("highlights")
        assert summary["highlights"][0]["key"] == "sentiment"
        assert len(summary["bullets"]) >= 1

    def test_rating_label_mapping(self) -> None:
        assert StockDiagnosisService._rating_label(7.5) == "偏强"
        assert StockDiagnosisService._rating_label(5.0) == "中性"
        assert StockDiagnosisService._rating_label(3.0) == "偏弱"
        assert StockDiagnosisService._rating_label(None) is None


class TestStockDiagnosisPhase4API:

    @pytest.mark.asyncio(loop_scope="session")
    async def test_diagnosis_has_phase4_fields(self, api_client: httpx.AsyncClient) -> None:
        response = await api_client.get(f"{API_PREFIX}/stocks/{SYMBOL}/diagnosis", timeout=30.0)
        assert response.status_code == 200
        data = response.json()["data"]
        assert "rating_label" in data
        assert data["rating_label"] in {"偏强", "中性", "偏弱", None}
        assert "module_scores" in data
        assert len(data["module_scores"]) == 6
        institutional = next(m for m in data["module_scores"] if m["key"] == "institutional")
        assert isinstance(institutional.get("detail", {}).get("earnings_preview"), list)
        summary = data["summary"]
        assert "bullets" in summary
        if summary.get("narrative"):
            assert isinstance(summary["narrative"], str)
        if summary.get("highlights"):
            assert isinstance(summary["highlights"], list)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_trigger_diagnosis_summary_enqueue(self, api_client: httpx.AsyncClient) -> None:
        response = await api_client.post(
            f"{API_PREFIX}/stocks/{SYMBOL}/diagnosis/summary",
            timeout=30.0,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["symbol"] == SYMBOL
        assert data["status"] == "PENDING"
        assert data.get("task_id")
