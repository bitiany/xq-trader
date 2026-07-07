"""OpenAPI parameters/requestBody -> MCP inputSchema 通用映射。"""

from __future__ import annotations

from typing import Any

from mcp_server.openapi.operation import Operation, Parameter


def build_input_schema(op: Operation, *, hide_params: list[str] | None = None) -> dict[str, Any]:
    """将 operation 的所有入参合并为单个 JSON Schema (object)。"""

    hidden = set(hide_params or ())
    properties: dict[str, Any] = {}
    required: list[str] = []
    for p in op.parameters:
        if p.name in hidden:
            continue
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
        # 与 HttpInvoker._partition 的容忍契约保持一致：未声明的入参由调用器静默丢弃，
        # 不在 schema 层硬拒绝，避免单个幻觉字段（如 limit）导致整次调用失败而丢失真实数据。
        "additionalProperties": True,
    }
    if required:
        schema["required"] = required
    return schema


def _parameter_schema(p: Parameter) -> dict[str, Any]:
    base = dict(p.schema) if p.schema else {"type": "string"}
    # 参数已扁平化进单一 object，位置标记（[in=path] 等）对模型无意义且会诱导其虚构 path/query 字段。
    base["description"] = p.description or p.name
    return base


def _schema_with_description(schema: dict[str, Any], extra: str) -> dict[str, Any]:
    out = dict(schema)
    existing = out.get("description") or ""
    out["description"] = f"{existing}\n{extra}".strip() if existing else extra
    return out
