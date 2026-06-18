"""单分组 -> 单 MCP Server 工厂。"""

from __future__ import annotations

import json
import re
from typing import Any

import mcp.types as mcp_types
from mcp.server.lowlevel import Server

from framework.commons.logger import get_logger
from mcp_server.config import ServerSection
from mcp_server.filter.grouper import GroupBundle
from mcp_server.invoker.http_invoker import HttpInvoker, ToolInvocationError
from mcp_server.openapi.operation import Operation
from mcp_server.schema.mapper import build_input_schema

logger = get_logger("MCP_FACTORY")

_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _sanitize(name: str) -> str:
    cleaned = _SANITIZE_RE.sub("_", name)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "unnamed_tool"


class GroupServerFactory:
    """根据分组结果构建一个独立的 MCP Server 实例。"""

    def __init__(self, server_cfg: ServerSection, invoker: HttpInvoker) -> None:
        self._cfg = server_cfg
        self._invoker = invoker

    def create(self, bundle: GroupBundle) -> Server[Any, Any]:
        server_name = f"{self._cfg.name}-{bundle.name}"
        server: Server[Any, Any] = Server(server_name)
        op_index = self._build_index(bundle.operations)

        @server.list_tools()
        async def _list_tools() -> list[mcp_types.Tool]:
            return [self._to_tool(name, op) for name, op in op_index.items()]

        @server.call_tool()
        async def _call_tool(
            name: str,
            arguments: dict[str, Any] | None,
        ) -> list[mcp_types.ContentBlock]:
            op = op_index.get(name)
            if op is None:
                raise ToolInvocationError(f"工具不存在: {name}")
            result = await self._invoker.invoke(op, arguments or {})
            text = json.dumps(result, ensure_ascii=False, default=str)
            return [mcp_types.TextContent(type="text", text=text)]

        logger.info(
            "Group %s server built: tools=%d names=%s",
            bundle.name,
            len(op_index),
            list(op_index.keys()),
        )
        return server

    def _build_index(self, operations: list[Operation]) -> dict[str, Operation]:
        index: dict[str, Operation] = {}
        prefix = self._cfg.tool_name_prefix
        for op in operations:
            base = op.operation_id or op.fallback_id
            tool_name = _sanitize(f"{prefix}{base}")
            if tool_name in index:
                logger.warning("Duplicate tool name within group: %s", tool_name)
                continue
            index[tool_name] = op
        return index

    @staticmethod
    def _to_tool(name: str, op: Operation) -> mcp_types.Tool:
        description_parts: list[str] = []
        if op.summary:
            description_parts.append(op.summary)
        if op.description:
            description_parts.append(op.description)
        description_parts.append(f"HTTP: {op.method} {op.path}")
        if op.tags:
            description_parts.append(f"Tags: {', '.join(op.tags)}")
        return mcp_types.Tool(
            name=name,
            description="\n\n".join(description_parts),
            inputSchema=build_input_schema(op),
        )
