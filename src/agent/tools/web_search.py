"""web_search Tool — 网络搜索（自定义封装，兼容 OpenAI function calling 格式）。"""

from __future__ import annotations

import json
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词，如'贵州茅台 最新消息'或'白酒行业 政策 2026'",
            },
        },
        "required": ["query"],
    }
)
class WebSearchCustomTool(Tool):
    _plugin_discoverable = False
    _scopes = {"core"}
    config_key = ""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "搜索网络获取最新新闻、公告、研报等资讯。"
            "返回搜索结果的标题、URL和摘要。"
            "仅接受query参数，不要传入其他参数。"
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> str:
        query = kwargs.get("query", "")
        if not query:
            return json.dumps({"error": "query 参数不能为空"}, ensure_ascii=False)

        try:
            from nanobot.agent.tools.web import WebSearchTool

            tool = WebSearchTool()
            result = await tool.execute(query=query)
            return str(result)
        except Exception as exc:
            return json.dumps({"error": f"搜索失败: {exc}"}, ensure_ascii=False)
