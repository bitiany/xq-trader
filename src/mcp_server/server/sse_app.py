"""多分组 SSE 应用 — 为每个 group 暴露独立 /sse/<group> 端点。"""

from __future__ import annotations

from typing import Any

from mcp.server.lowlevel import NotificationOptions
from mcp.server.lowlevel import Server as McpServer
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from framework.commons.logger import get_logger
from mcp_server.config import ServerSection

logger = get_logger("MCP_SSE_APP")


class MultiGroupSseApp:
    """根据分组装配 Starlette 应用：

    /sse/<group>           -> SSE GET 端点（每个 group 独立 transport 实例）
    /messages/<group>/     -> POST 消息端点
    /sse                   -> default_group 的别名（如果配置了）
    """

    def __init__(
        self,
        server_cfg: ServerSection,
        servers: dict[str, McpServer[Any, Any]],
    ) -> None:
        self._cfg = server_cfg
        self._servers = servers
        self._transports: dict[str, SseServerTransport] = {}

    def build(self) -> Starlette:
        routes: list[Route | Mount] = []
        prefix = self._cfg.routes_prefix.rstrip("/")
        for group_name, server in self._servers.items():
            messages_path = f"/messages/{group_name}/"
            transport = SseServerTransport(messages_path)
            self._transports[group_name] = transport
            routes.append(
                Route(
                    f"{prefix}/{group_name}",
                    endpoint=self._make_sse_endpoint(group_name, server, transport),
                    methods=["GET"],
                ),
            )
            routes.append(
                Mount(messages_path, app=transport.handle_post_message),
            )
            logger.info(
                "Mounted group=%s at %s/%s (post=%s)",
                group_name,
                prefix,
                group_name,
                messages_path,
            )

        default = self._cfg.default_group
        if default and default in self._servers:
            routes.append(
                Route(
                    prefix,
                    endpoint=self._make_sse_endpoint(
                        default,
                        self._servers[default],
                        self._transports[default],
                    ),
                    methods=["GET"],
                ),
            )
            logger.info("Default group %s aliased at %s", default, prefix)

        return Starlette(routes=routes)

    @staticmethod
    def _make_sse_endpoint(
        group_name: str,
        server: McpServer[Any, Any],
        transport: SseServerTransport,
    ) -> Any:
        async def _endpoint(request: Request) -> Response:
            # NOTE: request._send 是 MCP SDK SSE 示例的标准用法，
            # Starlette 未公开此属性但 SDK 依赖它传递 ASGI send。
            async with transport.connect_sse(
                request.scope, request.receive, request._send,
            ) as streams:
                init_options = server.create_initialization_options(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                )
                await server.run(streams[0], streams[1], init_options)
            return Response()

        _endpoint.__name__ = f"sse_endpoint_{group_name}"
        return _endpoint
