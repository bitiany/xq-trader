"""OpenAPI 文档加载与扁平化。"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import httpx
import yaml  # type: ignore[import-untyped]

from framework.commons.logger import get_logger
from mcp_server.config import SourceSection
from mcp_server.openapi.operation import Operation, Parameter

logger = get_logger("MCP_OPENAPI_LOADER")

_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}


class OpenApiLoader:
    """OpenAPI 文档加载器，支持 http / file 源；负责 $ref 解引与 operation 抽取。"""

    def __init__(self, source: SourceSection) -> None:
        self._source = source
        self._cached_doc: dict[str, Any] | None = None

    async def load(self) -> dict[str, Any]:
        """获取原始 OpenAPI 文档。"""

        if self._cached_doc is not None and self._source.refresh_interval == 0:
            return self._cached_doc

        if self._source.type == "http":
            doc = await self._load_http(self._source.url)
        else:
            doc = self._load_file(Path(self._source.path))

        if not isinstance(doc, dict) or "paths" not in doc:
            raise ValueError("OpenAPI 文档格式不合法：缺少 paths 节点")

        self._cached_doc = doc
        logger.info(
            "Loaded OpenAPI: title=%s version=%s paths=%d",
            doc.get("info", {}).get("title", ""),
            doc.get("info", {}).get("version", ""),
            len(doc.get("paths", {})),
        )
        return doc

    async def list_operations(self) -> list[Operation]:
        """从文档中抽取所有 Operation 并完成 $ref 解引。"""

        doc = await self.load()
        ops: list[Operation] = []
        for raw_path, path_item in doc.get("paths", {}).items():
            if not isinstance(path_item, dict):
                continue
            for method, op_raw in path_item.items():
                if method.lower() not in _HTTP_METHODS:
                    continue
                if not isinstance(op_raw, dict):
                    continue
                ops.append(self._build_operation(raw_path, method.upper(), op_raw, doc))
        return ops

    @staticmethod
    async def _load_http(url: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data: Any = resp.json()
            if not isinstance(data, dict):
                raise ValueError(f"OpenAPI 响应不是 JSON 对象: {url}")
            return data

    @staticmethod
    def _load_file(path: Path) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8")
        data: Any
        if path.suffix.lower() in {".yaml", ".yml"}:
            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"OpenAPI 文件不是 JSON/YAML 对象: {path}")
        return data

    def _build_operation(
        self,
        path: str,
        method: str,
        op_raw: dict[str, Any],
        doc: dict[str, Any],
    ) -> Operation:
        op_id = op_raw.get("operationId") or ""
        params = [
            self._build_parameter(self._resolve_ref(p, doc))
            for p in op_raw.get("parameters", [])
            if isinstance(p, dict)
        ]
        body_schema, body_required = self._extract_body(op_raw, doc)
        return Operation(
            operation_id=op_id,
            method=method,
            path=path,
            summary=op_raw.get("summary", "") or "",
            description=op_raw.get("description", "") or "",
            tags=list(op_raw.get("tags", []) or []),
            parameters=params,
            body_schema=body_schema,
            body_required=body_required,
        )

    @staticmethod
    def _build_parameter(p: dict[str, Any]) -> Parameter:
        return Parameter(
            name=str(p.get("name", "")),
            location=str(p.get("in", "query")),
            required=bool(p.get("required", False)),
            schema=dict(p.get("schema", {}) or {}),
            description=str(p.get("description", "") or ""),
        )

    def _extract_body(
        self,
        op_raw: dict[str, Any],
        doc: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, bool]:
        body = op_raw.get("requestBody")
        if not isinstance(body, dict):
            return None, False
        body = self._resolve_ref(body, doc)
        content = body.get("content", {})
        json_block = content.get("application/json") if isinstance(content, dict) else None
        if not isinstance(json_block, dict):
            return None, False
        schema = self._resolve_ref(json_block.get("schema", {}) or {}, doc)
        return (schema if isinstance(schema, dict) else None), bool(body.get("required", False))

    def _resolve_ref(self, node: Any, doc: dict[str, Any]) -> Any:
        """递归解引 $ref，避免出现 ref 留存在 schema 中。"""

        if isinstance(node, dict):
            if "$ref" in node and isinstance(node["$ref"], str):
                target = self._lookup_ref(node["$ref"], doc)
                return self._resolve_ref(deepcopy(target), doc)
            return {k: self._resolve_ref(v, doc) for k, v in node.items()}
        if isinstance(node, list):
            return [self._resolve_ref(i, doc) for i in node]
        return node

    @staticmethod
    def _lookup_ref(ref: str, doc: dict[str, Any]) -> Any:
        if not ref.startswith("#/"):
            raise ValueError(f"仅支持本文档内 $ref，收到: {ref}")
        cur: Any = doc
        for part in ref[2:].split("/"):
            if not isinstance(cur, dict) or part not in cur:
                raise ValueError(f"$ref 解析失败: {ref}")
            cur = cur[part]
        return cur
