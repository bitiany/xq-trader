"""xqtrader-mcp 进程入口。"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import uvicorn

from framework.commons.logger import get_logger
from mcp_server.config import McpServerConfig, load_config
from mcp_server.filter.grouper import OperationGrouper
from mcp_server.invoker.http_invoker import HttpInvoker
from mcp_server.openapi.loader import OpenApiLoader
from mcp_server.server.factory import GroupServerFactory
from mcp_server.server.sse_app import MultiGroupSseApp

logger = get_logger("MCP_MAIN")

_DEFAULT_CONFIG = "mcp_server.yml"


async def _build_app(cfg: McpServerConfig) -> tuple[uvicorn.Config, HttpInvoker]:
    loader = OpenApiLoader(cfg.source)
    operations = await loader.list_operations()
    logger.info("Total operations from OpenAPI: %d", len(operations))

    grouper = OperationGrouper(deny=cfg.deny, groups=cfg.groups)
    bundles = grouper.group(operations)

    invoker = HttpInvoker(cfg.source.api_base_url, cfg.invoker)
    factory = GroupServerFactory(cfg.server, invoker)

    servers = {bundle.name: factory.create(bundle) for bundle in bundles}
    starlette_app = MultiGroupSseApp(cfg.server, servers).build()

    uv_cfg = uvicorn.Config(
        starlette_app,
        host=cfg.server.host,
        port=cfg.server.port,
        log_level="info",
    )
    return uv_cfg, invoker


async def _serve(config_path: Path) -> None:
    cfg = load_config(config_path)
    uv_cfg, invoker = await _build_app(cfg)
    server = uvicorn.Server(uv_cfg)
    try:
        await server.serve()
    finally:
        await invoker.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="xqtrader OpenAPI -> MCP server")
    parser.add_argument(
        "--config",
        "-c",
        default=_DEFAULT_CONFIG,
        help="配置文件路径 (默认: mcp_server.yml)",
    )
    args = parser.parse_args()
    asyncio.run(_serve(Path(args.config)))


if __name__ == "__main__":
    main()
