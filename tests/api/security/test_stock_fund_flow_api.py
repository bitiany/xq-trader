"""个股资金流 API 与 MCP 工具 schema 黑盒测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
import yaml  # type: ignore[import-untyped]

from mcp_server.config import SourceSection, ToolOverride
from mcp_server.openapi.loader import OpenApiLoader
from mcp_server.openapi.operation import Operation
from mcp_server.schema.mapper import build_input_schema
from mcp_server.server.factory import _merge_invoke_arguments
from xqtrader.main import create_app

API_PREFIX = "/api/v1"
SYMBOL = "603993.SH"


def _load_fund_flow_operation() -> Operation:
    app = create_app()
    doc = app.openapi()
    loader = OpenApiLoader(SourceSection(type="http", url="http://unused"))
    loader._cached_doc = doc  # type: ignore[attr-defined]
    operations = asyncio.run(loader.list_operations())
    return next(o for o in operations if o.operation_id == "get_stock_fund_flow")


class TestStockFundFlowAPI:

    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_stock_fund_flow(self, api_client: httpx.AsyncClient) -> None:
        response = await api_client.get(f"{API_PREFIX}/stocks/{SYMBOL}/fund-flow")
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["symbol"] == SYMBOL
        assert isinstance(data.get("items"), list)
        if data["items"]:
            item = data["items"][-1]
            assert "trade_date" in item
            assert "main_net_pct" in item
            assert "main_net_amt" in item


class TestStockFundFlowMcpSchema:

    def test_input_schema_only_symbol(self) -> None:
        op = _load_fund_flow_operation()
        schema = build_input_schema(op, hide_params=["limit"])
        assert schema["type"] == "object"
        assert set(schema.get("properties", {}).keys()) == {"symbol"}
        assert schema.get("required") == ["symbol"]
        assert schema.get("additionalProperties") is False

    def test_mcp_config_hides_limit_and_sets_default(self) -> None:
        raw = yaml.safe_load(Path("mcp_server.yml").read_text(encoding="utf-8"))
        tool = raw["groups"]["stocks"]["tools"]["get_stock_fund_flow"]
        assert tool["invoke"]["hide_params"] == ["limit"]
        assert tool["invoke"]["defaults"]["limit"] == 5
        override = ToolOverride.model_validate(tool)
        merged = _merge_invoke_arguments({"symbol": SYMBOL}, override)
        assert merged == {"symbol": SYMBOL, "limit": 5}

    def test_mcp_config_includes_fund_flow_tool(self) -> None:
        raw = yaml.safe_load(Path("mcp_server.yml").read_text(encoding="utf-8"))
        includes = {
            entry["operation_id"]
            for entry in raw["groups"]["stocks"]["include"]
            if "operation_id" in entry
        }
        assert "get_stock_fund_flow" in includes
