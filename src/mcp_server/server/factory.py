"""单分组 -> 单 MCP Server 工厂。"""

from __future__ import annotations

import json
import re
from typing import Any

import mcp.types as mcp_types
from mcp.server.lowlevel import Server

from framework.commons.logger import get_logger
from mcp_server.config import ServerSection, ToolOverride
from mcp_server.filter.grouper import GroupBundle
from mcp_server.invoker.http_invoker import HttpInvoker, ToolInvocationError
from mcp_server.openapi.operation import Operation
from mcp_server.response.transformer import ResponseTransformer, TransformError
from mcp_server.schema.mapper import build_input_schema

logger = get_logger("MCP_FACTORY")

_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _sanitize(name: str) -> str:
    cleaned = _SANITIZE_RE.sub("_", name)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "unnamed_tool"


def _merge_invoke_arguments(
    arguments: dict[str, Any],
    override: ToolOverride | None,
) -> dict[str, Any]:
    """LLM 显式传参优先，缺省项用 invoke.defaults 填充。"""
    merged = dict(arguments)
    if override is None:
        return merged
    for key, value in override.invoke.defaults.items():
        if key not in merged:
            merged[key] = value
    return merged


class GroupServerFactory:
    """根据分组结果构建一个独立的 MCP Server 实例。"""

    def __init__(self, server_cfg: ServerSection, invoker: HttpInvoker) -> None:
        self._cfg = server_cfg
        self._invoker = invoker

    def create(self, bundle: GroupBundle) -> Server[Any, Any]:
        server_name = f"{self._cfg.name}-{bundle.name}"
        server: Server[Any, Any] = Server(server_name)
        op_index = self._build_index(bundle.operations)
        tool_overrides = bundle.section.tools

        @server.list_tools()
        async def _list_tools() -> list[mcp_types.Tool]:
            return [
                self._to_tool(name, op, tool_overrides.get(op.operation_id))
                for name, op in op_index.items()
            ]

        @server.call_tool()
        async def _call_tool(
            name: str,
            arguments: dict[str, Any] | None,
        ) -> list[mcp_types.ContentBlock]:
            op = op_index.get(name)
            if op is None:
                raise ToolInvocationError(f"工具不存在: {name}")
            override = tool_overrides.get(op.operation_id)
            invoke_args = _merge_invoke_arguments(arguments or {}, override)
            result = await self._invoker.invoke(op, invoke_args)
            if override and override.response is not None:
                try:
                    result = ResponseTransformer.transform(
                        result,
                        override.response.jmespath,
                    )
                except TransformError as exc:
                    raise ToolInvocationError(str(exc)) from exc
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
    def _to_tool(
        name: str,
        op: Operation,
        override: ToolOverride | None,
    ) -> mcp_types.Tool:
        description_parts: list[str] = []
        if override and override.risk_level:
            description_parts.append(f"风险等级: {override.risk_level}")
        if override and override.description.strip():
            description_parts.append(override.description.strip())
        elif op.summary:
            description_parts.append(op.summary)
        if op.description and (not override or not override.description.strip()):
            description_parts.append(op.description)
        if override and override.response is not None:
            description_parts.append("响应经 MCP 视图 DSL 裁剪，字段名与 OpenAPI 原始 schema 不同。")
        description_parts.append(f"HTTP: {op.method} {op.path}")
        if op.tags:
            description_parts.append(f"Tags: {', '.join(op.tags)}")
        hide_params = override.invoke.hide_params if override else []
        return mcp_types.Tool(
            name=name,
            description="\n\n".join(description_parts),
            inputSchema=build_input_schema(op, hide_params=hide_params),
        )
