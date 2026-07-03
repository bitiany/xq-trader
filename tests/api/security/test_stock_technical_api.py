"""个股技术面综合诊断 API 与 MCP 工具 schema 黑盒测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]
import httpx

from mcp_server.config import SourceSection
from mcp_server.openapi.loader import OpenApiLoader
from mcp_server.openapi.operation import Operation
from mcp_server.schema.mapper import build_input_schema
from xqtrader.main import create_app

API_PREFIX = "/api/v1"
SYMBOL = "688322.SH"


def _load_technical_operation() -> Operation:
    app = create_app()
    doc = app.openapi()
    loader = OpenApiLoader(SourceSection(type="http", url="http://unused"))
    loader._cached_doc = doc  # type: ignore[attr-defined]
    operations = asyncio.run(loader.list_operations())
    return next(o for o in operations if o.operation_id == "get_stock_technical")


class TestStockTechnicalAPI:

    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_stock_technical(self, api_client: httpx.AsyncClient) -> None:
        response = await api_client.get(f"{API_PREFIX}/stocks/{SYMBOL}/technical")
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["symbol"] == SYMBOL
        assert "trend" in data
        assert "momentum" in data
        assert "volatility" in data
        assert "recent_bars" in data
        if data.get("available"):
            assert data["trend"].get("direction") is not None
            assert data["momentum"].get("macd") is not None
            assert isinstance(data["recent_bars"], list)
            vol = data["volatility"]
            if vol.get("available"):
                assert vol.get("atr_14") is not None
                assert vol.get("stop_distance") is not None


class TestStockTechnicalMcpSchema:

    def test_input_schema_only_symbol(self) -> None:
        """MCP 工具入参仅 symbol，避免 limit 校验失败与多余字段。"""
        op = _load_technical_operation()
        schema = build_input_schema(op)
        assert schema["type"] == "object"
        assert set(schema.get("properties", {}).keys()) == {"symbol"}
        assert schema.get("required") == ["symbol"]
        assert schema.get("additionalProperties") is False

    def test_mcp_config_uses_unified_technical_tool(self) -> None:
        raw = yaml.safe_load(Path("mcp_server.yml").read_text(encoding="utf-8"))
        includes = {
            entry["operation_id"]
            for entry in raw["groups"]["stocks"]["include"]
            if "operation_id" in entry
        }
        assert "get_stock_technical" in includes
        assert "get_stock_chanlun" in includes
        for removed in (
            "get_stock_kline",
            "get_stock_kline_bars",
            "get_stock_trend",
            "get_stock_momentum",
        ):
            assert removed not in includes
