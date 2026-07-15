"""通用 HTTP 调用器 — 共享连接池，参数按 location 分桶。"""

from __future__ import annotations

from typing import Any

import httpx

from framework.commons.logger import get_logger
from mcp_server.config import InvokerSection
from mcp_server.openapi.operation import Operation

logger = get_logger("MCP_INVOKER")


class ToolInvocationError(Exception):
    """工具调用失败 — 由 server 层映射为 MCP isError 响应。"""


class HttpInvoker:
    """异步 HTTP 调用器，进程级共享 httpx.AsyncClient。"""

    def __init__(self, base_url: str, section: InvokerSection) -> None:
        limits = httpx.Limits(max_keepalive_connections=section.max_keepalive_connections)
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=section.timeout_seconds,
            limits=limits,
        )
        self._unwrap = section.unwrap_response_data

    async def aclose(self) -> None:
        await self._client.aclose()

    async def invoke(self, op: Operation, arguments: dict[str, Any]) -> Any:
        """执行 OpenAPI operation 调用。"""

        path_params, query_params, header_params, body = self._partition(op, arguments or {})
        url = op.path.format(**path_params)
        logger.info("MCP invoke op=%s %s %s", op.operation_id, op.method, url)
        try:
            resp = await self._client.request(
                op.method,
                url,
                params=query_params or None,
                headers=header_params or None,
                json=body,
            )
        except httpx.HTTPError as exc:
            logger.error("HTTP error: op=%s url=%s", op.operation_id, url, exc_info=True)
            raise ToolInvocationError(f"HTTP 调用失败: {exc}") from exc

        if resp.status_code >= 400:
            raise ToolInvocationError(
                f"HTTP {resp.status_code} from {op.method} {url}: {resp.text[:512]}",
            )

        return self._parse_body(resp)

    def _partition(
        self,
        op: Operation,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Any]:
        path_params: dict[str, Any] = {}
        query_params: dict[str, Any] = {}
        header_params: dict[str, Any] = {}
        known = {p.name for p in op.parameters}
        if op.body_schema is not None:
            known.add("body")
        # 兼容调用方（nanobot）透传 spawn 上下文参数（label/task/symbol 等），
        # 静默丢弃未声明参数而非报错，与 inputSchema additionalProperties=True 对齐。
        for p in op.parameters:
            if p.name not in arguments:
                if p.required and p.location == "path":
                    raise ToolInvocationError(f"缺少必填路径参数: {p.name}")
                continue
            value = arguments[p.name]
            bucket = self._location_bucket(p.location, path_params, query_params, header_params)
            bucket[p.name] = value
        body = arguments.get("body")
        return path_params, query_params, header_params, body

    @staticmethod
    def _location_bucket(
        location: str,
        path_params: dict[str, Any],
        query_params: dict[str, Any],
        header_params: dict[str, Any],
    ) -> dict[str, Any]:
        mapping = {"path": path_params, "query": query_params, "header": header_params}
        if location not in mapping:
            raise ToolInvocationError(f"不支持的参数位置: {location}")
        return mapping[location]

    def _parse_body(self, resp: httpx.Response) -> Any:
        try:
            data: Any = resp.json()
        except ValueError:
            return resp.text
        if self._unwrap and isinstance(data, dict) and "data" in data:
            return data["data"]
        return data
