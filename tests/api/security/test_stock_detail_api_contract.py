"""个股详情页 API 契约一致性测试 — 与前端 TypeScript 类型对齐。"""

from __future__ import annotations

import httpx
import pytest

API_PREFIX = "/api/v1"
SYMBOL = "688322.SH"

_MODULE_KEYS = {
    "technical", "capital_flow", "fundamental", "sentiment", "industry", "institutional",
}

_DIAGNOSIS_REQUIRED = {
    "symbol", "name", "industry", "intro", "as_of", "overall_score",
    "prev_overall_score", "prev_as_of", "rating_label", "market_percentile",
    "module_scores", "key_metrics",
    "summary", "thesis", "reports_count", "cached",
}
_KEY_METRICS_REQUIRED = {
    "pe_ttm", "pb", "dv_ttm", "institutional_hold_pct",
    "industry_rank", "industry_total", "industry_name",
}
_SUMMARY_REQUIRED = {"bullets", "generated_by", "generated_at"}
_NEWS_ITEM_REQUIRED = {"id", "title", "source", "published_at", "summary", "url", "keywords"}


class TestStockDetailApiContract:

    @pytest.mark.asyncio(loop_scope="session")
    async def test_diagnosis_response_contract(self, api_client: httpx.AsyncClient) -> None:
        response = await api_client.get(f"{API_PREFIX}/stocks/{SYMBOL}/diagnosis", timeout=30.0)
        assert response.status_code == 200
        data = response.json()["data"]
        assert _DIAGNOSIS_REQUIRED.issubset(data.keys())
        assert isinstance(data["module_scores"], list)
        assert len(data["module_scores"]) == 6
        module_keys = {module["key"] for module in data["module_scores"]}
        assert module_keys == _MODULE_KEYS
        for module in data["module_scores"]:
            assert {"key", "label", "score", "prev_score", "weight", "detail"}.issubset(module.keys())

        metrics = data["key_metrics"]
        assert _KEY_METRICS_REQUIRED.issubset(metrics.keys())
        if metrics["institutional_hold_pct"] is not None:
            assert metrics.get("institutional_hold_source") == "fund"

        summary = data["summary"]
        assert _SUMMARY_REQUIRED.issubset(summary.keys())
        assert summary["generated_by"] in {"rule", "agent"}
        if summary.get("narrative") is not None:
            assert isinstance(summary["narrative"], str)
        if summary.get("highlights") is not None:
            assert isinstance(summary["highlights"], list)
            for item in summary["highlights"]:
                assert {"key", "label", "segments"}.issubset(item.keys())

        institutional = next(m for m in data["module_scores"] if m["key"] == "institutional")
        earnings_preview = institutional.get("detail", {}).get("earnings_preview")
        assert isinstance(earnings_preview, list)

        if data["rating_label"] is not None:
            assert data["rating_label"] in {"偏强", "中性", "偏弱"}

    @pytest.mark.asyncio(loop_scope="session")
    async def test_diagnosis_history_contract(self, api_client: httpx.AsyncClient) -> None:
        response = await api_client.get(
            f"{API_PREFIX}/stocks/{SYMBOL}/diagnosis/history",
            params={"days": 30},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["symbol"] == SYMBOL
        assert isinstance(data["items"], list)
        if data["items"]:
            item = data["items"][0]
            assert {"as_of", "overall_score", "modules"}.issubset(item.keys())

    @pytest.mark.asyncio(loop_scope="session")
    async def test_news_response_contract(self, api_client: httpx.AsyncClient) -> None:
        response = await api_client.get(f"{API_PREFIX}/stocks/{SYMBOL}/news")
        assert response.status_code == 200
        data = response.json()["data"]
        assert {"symbol", "items", "total"}.issubset(data.keys())
        assert data["total"] == len(data["items"])
        if data["items"]:
            assert _NEWS_ITEM_REQUIRED.issubset(data["items"][0].keys())

    @pytest.mark.asyncio(loop_scope="session")
    async def test_announcements_response_contract(self, api_client: httpx.AsyncClient) -> None:
        response = await api_client.get(f"{API_PREFIX}/stocks/{SYMBOL}/announcements")
        assert response.status_code == 200
        data = response.json()["data"]
        assert {"symbol", "items", "total"}.issubset(data.keys())
        assert data["total"] == len(data["items"])

    @pytest.mark.asyncio(loop_scope="session")
    async def test_financials_history_contract(self, api_client: httpx.AsyncClient) -> None:
        response = await api_client.get(f"{API_PREFIX}/stocks/{SYMBOL}/financials")
        assert response.status_code == 200
        data = response.json()["data"]
        assert "financial_indicator_history" in data
        assert isinstance(data["financial_indicator_history"], list)
