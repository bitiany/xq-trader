"""OpenAPI parameters/requestBody -> MCP inputSchema 通用映射。"""

from __future__ import annotations

from typing import Any

from mcp_server.openapi.operation import Operation, Parameter


def build_input_schema(op: Operation) -> dict[str, Any]:
    """将 operation 的所有入参合并为单个 JSON Schema (object)。"""

    properties: dict[str, Any] = {}
    required: list[str] = []
    for p in op.parameters:
        properties[p.name] = _parameter_schema(p)
        if p.required:
            required.append(p.name)

    if op.body_schema is not None:
        properties["body"] = _schema_with_description(op.body_schema, "请求体 (application/json)")
        if op.body_required:
            required.append("body")

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _parameter_schema(p: Parameter) -> dict[str, Any]:
    base = dict(p.schema) if p.schema else {"type": "string"}
    desc = p.description or f"{p.name} ({p.location})"
    base["description"] = (
        f"{desc} [in={p.location}]" if "[in=" not in desc else desc
    )
    return base


def _schema_with_description(schema: dict[str, Any], extra: str) -> dict[str, Any]:
    out = dict(schema)
    existing = out.get("description") or ""
    out["description"] = f"{existing}\n{extra}".strip() if existing else extra
    return out
