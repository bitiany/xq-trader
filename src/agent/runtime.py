"""Nanobot Runtime 工厂 — 通过 MCP 接入工具，不再注册自定义 HTTP 包装。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from nanobot.nanobot import Nanobot

from agent.config import agent_settings
from framework.commons.logger import get_logger

logger = get_logger("AGENT_RUNTIME")

_WORKSPACE = Path(agent_settings.WORKSPACE)
_CONFIG_PATH = _WORKSPACE / "config.json"


def _patch_nanobot_list_arguments() -> None:
    """Monkey-patch Nanobot 函数，处理 Qwen3 等模型返回 list 类型工具参数的问题。"""
    import nanobot.utils.runtime as _runtime_mod

    _orig_ext_sig = _runtime_mod.external_lookup_signature
    _orig_ws_sig = _runtime_mod.workspace_violation_signature

    def _safe_external_lookup_signature(
        tool_name: str, arguments: dict[str, Any],
    ) -> str | None:
        if isinstance(arguments, list):
            return None
        return _orig_ext_sig(tool_name, arguments)  # type: ignore[no-any-return]

    def _safe_workspace_violation_signature(
        tool_name: str, arguments: dict[str, Any],
    ) -> str | None:
        if isinstance(arguments, list):
            return None
        return _orig_ws_sig(tool_name, arguments)  # type: ignore[no-any-return]

    _runtime_mod.external_lookup_signature = _safe_external_lookup_signature
    _runtime_mod.workspace_violation_signature = _safe_workspace_violation_signature
    logger.info("Patched nanobot.utils.runtime for list-argument safety")

    import nanobot.agent.runner as _runner_mod

    _orig_run_tool = _runner_mod.AgentRunner._run_tool

    async def _safe_run_tool(
        self: _runner_mod.AgentRunner,
        spec: Any,
        tool_call: Any,
        ext_counts: dict[str, int],
        ws_counts: dict[str, int],
    ) -> Any:
        if isinstance(tool_call.arguments, list):
            merged: dict[str, Any] = {}
            for item in tool_call.arguments:
                if isinstance(item, dict):
                    for k, v in item.items():
                        if k not in merged:
                            merged[k] = v
            tool_call.arguments = merged
            logger.warning(
                "Normalized list arguments for tool %s -> %s",
                tool_call.name,
                list(merged.keys()),
            )
        return await _orig_run_tool(self, spec, tool_call, ext_counts, ws_counts)

    _runner_mod.AgentRunner._run_tool = _safe_run_tool
    logger.info("Patched nanobot.agent.runner.AgentRunner._run_tool for list-argument normalization")


def _build_mcp_servers() -> dict[str, dict[str, Any]]:
    """根据 MCP_GROUPS 配置生成 mcpServers 节点（多端点路由静态分流）。"""

    base = agent_settings.MCP_BASE_URL.rstrip("/")
    return {
        f"xq_{group}": {
            "type": "sse",
            "url": f"{base}/sse/{group}",
            "toolTimeout": agent_settings.MCP_TOOL_TIMEOUT,
            "enabledTools": ["*"],
        }
        for group in agent_settings.MCP_GROUPS
    }


def _write_runtime_config() -> None:
    _WORKSPACE.mkdir(parents=True, exist_ok=True)
    data = {
        "agents": {
            "defaults": {
                "workspace": str(_WORKSPACE),
                "model": agent_settings.LLM_MODEL_NAME,
                "provider": "custom",
                "max_tokens": 8192,
                "context_window_tokens": 65536,
                "temperature": 0.1,
                "max_tool_iterations": 30,
                "max_tool_result_chars": 16000,
                "timezone": "Asia/Shanghai",
                "disabled_skills": agent_settings.DISABLED_SKILLS,
            }
        },
        "providers": {
            "custom": {
                "api_key": agent_settings.LLM_API_KEY,
                "api_base": agent_settings.LLM_BASE_URL.rstrip("/"),
            }
        },
        "tools": {
            "web": {
                "enable": True,
                "search": {
                    "provider": os.getenv("AGENT_WEB_SEARCH_PROVIDER", "tavily"),
                    "api_key": os.getenv("TAVILY_API_KEY", os.getenv("BRAVE_API_KEY", "")),
                    "max_results": 5,
                    "timeout": 30,
                },
            },
            "exec": {"enable": False},
            "mcpServers": _build_mcp_servers(),
        },
    }
    _CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


_bot_cache: dict[str, Nanobot] = {}


def build_bot(*, model: str | None = None) -> Nanobot:
    effective_model = model or agent_settings.LLM_MODEL_NAME
    if effective_model in _bot_cache:
        return _bot_cache[effective_model]

    _write_runtime_config()
    bot = Nanobot.from_config(_CONFIG_PATH, workspace=_WORKSPACE)
    if effective_model:
        bot._loop.model = effective_model
    _bot_cache[effective_model] = bot
    logger.info(
        "Nanobot created: workspace=%s model=%s base=%s mcp_groups=%s",
        _WORKSPACE,
        bot._loop.model,
        agent_settings.LLM_BASE_URL,
        agent_settings.MCP_GROUPS,
    )
    return bot
