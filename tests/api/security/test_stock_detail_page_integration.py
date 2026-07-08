"""个股详情页全面集成测试 — 对照前端 StockDetailPage 实际调用的 API 黑盒验收。"""

from __future__ import annotations

import time

import httpx
import pytest

API_BASE = "http://127.0.0.1:8096"
API_PREFIX = "/api/v1"
SYMBOLS = ("688322.SH", "300433.SZ")

_OVERVIEW_REQUIRED = {"symbol", "name", "code", "market", "industry", "valuation"}
_DIAGNOSIS_REQUIRED = {
    "symbol", "name", "as_of", "overall_score", "rating_label", "market_percentile",
    "module_scores", "key_metrics", "summary", "reports_count", "cached",
}
_MODULE_KEYS = {
    "technical", "capital_flow", "fundamental", "sentiment", "industry", "institutional",
}
_KLINE_REQUIRED = {"symbol", "bars"}


def _assert_ok(response: httpx.Response, label: str) -> dict:
    assert response.status_code == 200, f"{label} HTTP {response.status_code}: {response.text[:300]}"
    body = response.json()
    assert body.get("code") == 0, f"{label} code={body.get('code')} msg={body.get('message')}"
    data = body.get("data")
    assert data is not None, f"{label} data 为空"
    return data


@pytest.fixture(scope="module")
def live_client() -> httpx.Client:
    with httpx.Client(base_url=API_BASE, timeout=120.0) as client:
        health = client.get(f"{API_PREFIX}/health")
        if health.status_code != 200:
            pytest.skip(f"API 未启动: {API_BASE}")
        yield client


class TestStockDetailPageLiveIntegration:

    @pytest.mark.parametrize("symbol", SYMBOLS)
    def test_overview(self, live_client: httpx.Client, symbol: str) -> None:
        data = _assert_ok(live_client.get(f"{API_PREFIX}/stocks/{symbol}"), f"overview {symbol}")
        assert _OVERVIEW_REQUIRED.issubset(data.keys())
        assert data["symbol"] == symbol

    @pytest.mark.parametrize("symbol", SYMBOLS)
    def test_kline(self, live_client: httpx.Client, symbol: str) -> None:
        data = _assert_ok(live_client.get(f"{API_PREFIX}/stocks/{symbol}/kline"), f"kline {symbol}")
        assert _KLINE_REQUIRED.issubset(data.keys())
        assert isinstance(data["bars"], list)
        assert len(data["bars"]) > 0

    @pytest.mark.parametrize("symbol", SYMBOLS)
    def test_fund_flow(self, live_client: httpx.Client, symbol: str) -> None:
        data = _assert_ok(
            live_client.get(f"{API_PREFIX}/stocks/{symbol}/fund-flow", params={"limit": 1200}),
            f"fund-flow {symbol}",
        )
        assert data["symbol"] == symbol
        assert isinstance(data.get("items"), list)

    @pytest.mark.parametrize("symbol", SYMBOLS)
    def test_financials(self, live_client: httpx.Client, symbol: str) -> None:
        data = _assert_ok(live_client.get(f"{API_PREFIX}/stocks/{symbol}/financials"), f"financials {symbol}")
        assert data["symbol"] == symbol
        assert isinstance(data.get("financial_indicator_history"), list)

    @pytest.mark.parametrize("symbol", SYMBOLS)
    def test_news(self, live_client: httpx.Client, symbol: str) -> None:
        data = _assert_ok(live_client.get(f"{API_PREFIX}/stocks/{symbol}/news"), f"news {symbol}")
        assert data["symbol"] == symbol
        assert data["total"] == len(data["items"])

    @pytest.mark.parametrize("symbol", SYMBOLS)
    def test_announcements(self, live_client: httpx.Client, symbol: str) -> None:
        data = _assert_ok(
            live_client.get(f"{API_PREFIX}/stocks/{symbol}/announcements"),
            f"announcements {symbol}",
        )
        assert data["symbol"] == symbol
        assert data["total"] == len(data["items"])

    @pytest.mark.parametrize("symbol", SYMBOLS)
    def test_diagnosis_cached(self, live_client: httpx.Client, symbol: str) -> None:
        data = _assert_ok(live_client.get(f"{API_PREFIX}/stocks/{symbol}/diagnosis"), f"diagnosis {symbol}")
        assert _DIAGNOSIS_REQUIRED.issubset(data.keys())
        assert len(data["module_scores"]) == 6
        module_keys = {module["key"] for module in data["module_scores"]}
        assert module_keys == _MODULE_KEYS
        assert isinstance(data["summary"].get("bullets"), list)
        institutional = next(m for m in data["module_scores"] if m["key"] == "institutional")
        assert isinstance(institutional.get("detail", {}).get("earnings_preview"), list)
        if data["rating_label"] is not None:
            assert data["rating_label"] in {"偏强", "中性", "偏弱"}

    @pytest.mark.parametrize("symbol", SYMBOLS)
    def test_diagnosis_history(self, live_client: httpx.Client, symbol: str) -> None:
        data = _assert_ok(
            live_client.get(f"{API_PREFIX}/stocks/{symbol}/diagnosis/history", params={"days": 90}),
            f"diagnosis/history {symbol}",
        )
        assert data["symbol"] == symbol
        assert isinstance(data["items"], list)

    @pytest.mark.parametrize("symbol", SYMBOLS)
    def test_diagnosis_history_365_for_reports_drawer(self, live_client: httpx.Client, symbol: str) -> None:
        data = _assert_ok(
            live_client.get(f"{API_PREFIX}/stocks/{symbol}/diagnosis/history", params={"days": 365}),
            f"diagnosis/history365 {symbol}",
        )
        assert data["symbol"] == symbol

    def test_diagnosis_cache_latency(self, live_client: httpx.Client) -> None:
        symbol = SYMBOLS[0]
        start = time.perf_counter()
        _assert_ok(live_client.get(f"{API_PREFIX}/stocks/{symbol}/diagnosis"), "diagnosis cache")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 500, f"诊股缓存路径过慢: {elapsed_ms:.1f}ms"

    def test_diagnosis_summary_enqueue(self, live_client: httpx.Client) -> None:
        symbol = SYMBOLS[0]
        data = _assert_ok(
            live_client.post(f"{API_PREFIX}/stocks/{symbol}/diagnosis/summary"),
            "diagnosis/summary POST",
        )
        assert data["symbol"] == symbol
        assert data["status"] == "PENDING"
        assert data.get("task_id")

    @pytest.mark.parametrize("symbol", SYMBOLS)
    def test_research_reports_for_earnings_drawer(self, live_client: httpx.Client, symbol: str) -> None:
        response = live_client.get(f"{API_PREFIX}/research/reports", params={"symbol": symbol, "page_size": 20})
        data = _assert_ok(response, f"research/reports {symbol}")
        assert "items" in data
        assert "total" in data
