"""HttpInvoker 参数校验单元测试。"""

from __future__ import annotations

import pytest

from mcp_server.invoker.http_invoker import HttpInvoker, ToolInvocationError
from mcp_server.openapi.operation import Operation, Parameter


def _fund_flow_operation() -> Operation:
    return Operation(
        operation_id="get_stock_fund_flow",
        method="GET",
        path="/api/v1/stocks/{symbol}/fund-flow",
        parameters=[
            Parameter(
                name="symbol",
                location="path",
                required=True,
                schema={"type": "string"},
            ),
            Parameter(
                name="limit",
                location="query",
                required=False,
                schema={"type": "integer"},
            ),
        ],
    )


def test_partition_rejects_unknown_arguments() -> None:
    invoker = HttpInvoker("http://unused", _invoker_section())
    with pytest.raises(ToolInvocationError, match="不支持的参数"):
        invoker._partition(_fund_flow_operation(), {"symbol": "603993.SH", "foo": 1})


def test_partition_accepts_declared_arguments() -> None:
    invoker = HttpInvoker("http://unused", _invoker_section())
    path, query, _headers, body = invoker._partition(
        _fund_flow_operation(),
        {"symbol": "603993.SH", "limit": 5},
    )
    assert path == {"symbol": "603993.SH"}
    assert query == {"limit": 5}
    assert body is None


def _invoker_section() -> object:
    from mcp_server.config import InvokerSection

    return InvokerSection(timeout_seconds=5.0)
