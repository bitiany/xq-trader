"""Nanobot 运行时适配 — 集中管理对上游框架的必要补丁。"""

from __future__ import annotations

from typing import Any

from agent.config import agent_settings
from framework.commons.logger import get_logger

logger = get_logger("AGENT_NANOBOT_PATCHES")

_applied = False


class NanobotRuntimePatches:
    """一次性应用 Nanobot 运行时补丁（Qwen3 list 参数、子 Agent 迭代预算）。"""

    @classmethod
    def apply(cls) -> None:
        global _applied
        if _applied:
            return
        cls._patch_list_arguments()
        cls._patch_subagent_limits()
        _applied = True

    @staticmethod
    def _patch_list_arguments() -> None:
        import nanobot.utils.runtime as _runtime_mod

        _orig_ext_sig = _runtime_mod.external_lookup_signature
        _orig_ws_sig = _runtime_mod.workspace_violation_signature

        def _safe_external_lookup_signature(
            tool_name: str,
            arguments: dict[str, Any],
        ) -> str | None:
            if isinstance(arguments, list):
                return None
            return _orig_ext_sig(tool_name, arguments)  # type: ignore[no-any-return]

        def _safe_workspace_violation_signature(
            tool_name: str,
            arguments: dict[str, Any],
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
                        for key, value in item.items():
                            if key not in merged:
                                merged[key] = value
                tool_call.arguments = merged
                logger.warning(
                    "Normalized list arguments for tool %s -> %s",
                    tool_call.name,
                    list(merged.keys()),
                )
            return await _orig_run_tool(self, spec, tool_call, ext_counts, ws_counts)

        _runner_mod.AgentRunner._run_tool = _safe_run_tool
        logger.info(
            "Patched nanobot.agent.runner.AgentRunner._run_tool for list-argument normalization",
        )

    @staticmethod
    def _patch_subagent_limits() -> None:
        import nanobot.agent.loop as _loop_mod

        def _sync_subagent_limits(self: _loop_mod.AgentLoop) -> None:
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
