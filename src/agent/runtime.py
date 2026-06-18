"""Nanobot Runtime 工厂。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nanobot.nanobot import Nanobot

from agent.config import agent_settings
from agent.tools.stock_financials import GetStockFinancialsTool
from agent.tools.stock_fund_flow import GetStockFundFlowTool
from agent.tools.stock_overview import GetStockOverviewTool
from agent.tools.stock_position import GetStockPositionTool
from agent.tools.stock_technicals import GetStockTechnicalsTool
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
            }
        },
        "providers": {
            "custom": {
                "api_key": agent_settings.LLM_API_KEY,
                "api_base": agent_settings.LLM_BASE_URL.rstrip("/"),
            }
        },
        "tools": {
            "web": {"enable": True},
            "exec": {"enable": False},
        },
    }
    _CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _register_custom_tools(bot: Nanobot) -> None:
    registry = bot._loop.tools
    logger.info("Registered tools before custom: %s", registry.tool_names)
    for tool_cls in (
        GetStockOverviewTool,
        GetStockFinancialsTool,
        GetStockTechnicalsTool,
        GetStockPositionTool,
        GetStockFundFlowTool,
    ):
        instance = tool_cls()
        registry.register(instance)
        logger.info("Registered custom tool: %s", instance.name)

    _register_web_tools(registry)


def _register_web_tools(registry: Any) -> None:
    from agent.tools.web_search import WebSearchCustomTool

    search_tool = WebSearchCustomTool()
    registry.register(search_tool)
    logger.info("Registered custom tool: %s", search_tool.name)


_bot_cache: dict[str, Nanobot] = {}


def build_bot(*, model: str | None = None) -> Nanobot:
    effective_model = model or agent_settings.LLM_MODEL_NAME
    if effective_model in _bot_cache:
        return _bot_cache[effective_model]

    _write_runtime_config()
    bot = Nanobot.from_config(_CONFIG_PATH, workspace=_WORKSPACE)
    if effective_model:
        bot._loop.model = effective_model
    _register_custom_tools(bot)
    _bot_cache[effective_model] = bot
    logger.info(
        "Nanobot created: workspace=%s model=%s base=%s",
        _WORKSPACE,
        bot._loop.model,
        agent_settings.LLM_BASE_URL,
    )
    return bot
