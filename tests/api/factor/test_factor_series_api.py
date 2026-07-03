"""因子宽表时序 API 与 MCP schema 黑盒测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
import yaml  # type: ignore[import-untyped]

from mcp_server.config import SourceSection
from mcp_server.openapi.loader import OpenApiLoader
from mcp_server.openapi.operation import Operation
from mcp_server.schema.mapper import build_input_schema
from xqtrader.main import create_app

API_PREFIX = "/api/v1"
SYMBOL = "688322.SH"


def _load_factor_series_operation() -> Operation:
    app = create_app()
    doc = app.openapi()
    loader = OpenApiLoader(SourceSection(type="http", url="http://unused"))
    loader._cached_doc = doc  # type: ignore[attr-defined]
    operations = asyncio.run(loader.list_operations())
    return next(o for o in operations if o.operation_id == "get_stock_factor_series")


class TestStockFactorSeriesAPI:

    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_stock_factor_series_wide(self, api_client: httpx.AsyncClient) -> None:
        response = await api_client.get(f"{API_PREFIX}/factors/series/{SYMBOL}")
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["symbol"] == SYMBOL
        assert data["factor_count"] == len(data["factors"])
        assert data["columns"][0] == "trade_date"
        assert len(data["columns"]) == 1 + len(data["factors"])
        if data["rows"]:
            row = data["rows"][-1]
            assert "trade_date" in row
            sample_factor_id = data["factors"][0]["factor_id"]
            assert sample_factor_id in row

    @pytest.mark.asyncio(loop_scope="session")
    async def test_factor_meta_contains_description(self, api_client: httpx.AsyncClient) -> None:
        response = await api_client.get(f"{API_PREFIX}/factors/series/{SYMBOL}")
        data = response.json()["data"]
        assert data["factors"]
        first = data["factors"][0]
        assert "factor_id" in first
        assert "display_name" in first
        assert "description" in first


class TestStockFactorSeriesMcpSchema:

    def test_input_schema_only_symbol_and_optional_dates(self) -> None:
        op = _load_factor_series_operation()
        schema = build_input_schema(op)
        props = set(schema.get("properties", {}).keys())
        assert "symbol" in props
        assert props <= {"symbol", "start_date", "end_date", "pool_id"}
        assert schema.get("required") == ["symbol"]
        assert schema.get("additionalProperties") is False

    def test_mcp_config_uses_unified_factor_tool(self) -> None:
        raw = yaml.safe_load(Path("mcp_server.yml").read_text(encoding="utf-8"))
        includes = {
            entry["operation_id"]
            for entry in raw["groups"]["factors"]["include"]
            if "operation_id" in entry
        }
        assert includes == {"get_stock_factor_series"}
