"""MCP 响应视图转换 — 按配置 DSL 裁剪 API 结果。"""

from mcp_server.response.transformer import ResponseTransformer, TransformError

__all__ = ["ResponseTransformer", "TransformError"]
