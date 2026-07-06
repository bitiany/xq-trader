"""Nanobot Runtime 工厂 — 通过 MCP 接入工具，不再注册自定义 HTTP 包装。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from nanobot.agent.loop import AgentLoop
from nanobot.config.loader import load_config, resolve_config_env_vars
from nanobot.config.schema import Config
from nanobot.nanobot import Nanobot
from nanobot.providers.image_generation import image_gen_provider_configs

from agent.config import agent_settings
from agent.session_backend import PgSessionManager
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

    import nanobot.agent.loop as _loop_mod

    def _sync_subagent_limits(self: _loop_mod.AgentLoop) -> None:
        """Orchestrator 与 spawn Worker 使用独立迭代预算。"""
        self.subagents.max_iterations = agent_settings.MAX_SUBAGENT_ITERATIONS
        self.subagents.max_concurrent_subagents = (
            agent_settings.MAX_CONCURRENT_SUBAGENTS
        )

    _loop_mod.AgentLoop._sync_subagent_runtime_limits = _sync_subagent_limits
    logger.info(
        "Patched AgentLoop subagent limits: iterations=%s concurrent=%s",
        agent_settings.MAX_SUBAGENT_ITERATIONS,
        agent_settings.MAX_CONCURRENT_SUBAGENTS,
    )


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
                "max_tool_iterations": agent_settings.MAX_TOOL_ITERATIONS,
                "max_concurrent_subagents": agent_settings.MAX_CONCURRENT_SUBAGENTS,
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


_bot: Nanobot | None = None
_session_manager: PgSessionManager | None = None
_runtime_initialized = False


def init_runtime() -> None:
    """Worker 启动时一次性初始化：patch nanobot + 同步 config.json。"""
    global _runtime_initialized
    if _runtime_initialized:
        return
    _patch_nanobot_list_arguments()
    _write_runtime_config()
    _runtime_initialized = True


def get_pg_session_manager() -> PgSessionManager:
    """返回全局 PgSessionManager（与 build_bot 共享同一实例与连接池）。"""
    if _session_manager is None:
        build_bot()
    assert _session_manager is not None
    return _session_manager


def build_bot(*, model: str | None = None) -> Nanobot:
    """构建或复用 Nanobot 实例。

    全局仅缓存一个 Nanobot（含 PgSessionManager / MCP 连接），切换模型时仅替换
    bot._loop.model，避免多实例跨 event loop 的 Future 绑定冲突。
    """
    global _bot, _session_manager
    effective_model = model or agent_settings.LLM_MODEL_NAME

    if _bot is None:
        _write_runtime_config()
        config: Config = resolve_config_env_vars(load_config(_CONFIG_PATH))
        config.agents.defaults.workspace = str(_WORKSPACE)
        session_manager = PgSessionManager(_WORKSPACE)
        _session_manager = session_manager
        loop = AgentLoop.from_config(
            config,
            session_manager=session_manager,
            image_generation_provider_configs=image_gen_provider_configs(config),
        )
        _bot = Nanobot(loop)
        logger.info(
            "Nanobot created (PG session backend): workspace=%s model=%s base=%s mcp_groups=%s",
            _WORKSPACE,
            effective_model,
            agent_settings.LLM_BASE_URL,
            agent_settings.MCP_GROUPS,
        )

    _bot._loop.model = effective_model
    return _bot
