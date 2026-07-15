"""Nanobot 运行时适配 - 集中管理对上游框架的必要补丁。"""

from __future__ import annotations

import asyncio
from typing import Any

from agent.config import agent_settings
from framework.commons.logger import get_logger

logger = get_logger("AGENT_NANOBOT_PATCHES")

_applied = False


class NanobotRuntimePatches:
    """一次性应用 Nanobot 运行时补丁（Qwen3 list 参数、子 Agent 迭代预算、子 Agent MCP 工具注入）。"""

    @classmethod
    def apply(cls) -> None:
        global _applied
        if _applied:
            return
        cls._patch_list_arguments()
        cls._patch_subagent_limits()
        cls._patch_subagent_mcp_tools()
        cls._patch_llm_error_subagent_wait()
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

    @staticmethod
    def _patch_subagent_mcp_tools() -> None:
        """补丁 SubagentManager._build_tools，使子 Agent 也能使用主 Agent 的 MCP 工具。

        Nanobot 原生 SubagentManager 创建隔离的 ToolRegistry，只加载 scope="subagent"
        的内置工具（read_file/web_search 等），排除所有 MCP 工具。这导致 spawn Worker
        无法调用 get_stock_technical 等业务 MCP 工具，只能用 web_search 盲目搜索。

        修复：在 _build_tools 完成内置工具加载后，将主 AgentLoop 的 MCP 工具引用
        复制到子 Agent 的 ToolRegistry。MCP 工具是无状态 HTTP 客户端，共享安全。
        """
        import nanobot.agent.subagent as _subagent_mod

        _orig_build_tools = _subagent_mod.SubagentManager._build_tools

        def _build_tools_with_mcp(
            self: _subagent_mod.SubagentManager,
            workspace: Any | None = None,
            tools_config: Any | None = None,
        ) -> Any:
            registry = _orig_build_tools(self, workspace, tools_config)
            mcp_source = getattr(self, "_mcp_tools_source", None)
            if mcp_source is None:
                return registry
            added: list[str] = []
            for name in mcp_source.tool_names:
                if name.startswith("mcp_") and not registry.has(name):
                    tool = mcp_source.get(name)
                    if tool is not None:
                        registry.register(tool)
                        added.append(name)
            if added:
                logger.info(
                    "Subagent tool registry enriched with %d MCP tools: %s",
                    len(added),
                    added[:10],
                )
            return registry

        _subagent_mod.SubagentManager._build_tools = _build_tools_with_mcp
        logger.info("Patched SubagentManager._build_tools for MCP tool injection")

    @staticmethod
    def _patch_llm_error_subagent_wait() -> None:
        """补丁 AgentLoop.process_direct 和 SubagentManager._announce_result。

        Nanobot SDK 模式（process_direct）有两个结构性缺陷：

        1. process_direct 不创建 pending_queue -> _drain_pending 收到 None
           直接返回空，子 Agent 结果无法 mid-turn 注入。

        2. AgentLoop.run()（消息总线消费器）在 SDK 模式下未启动 ->
           _announce_result 发布到 bus 的消息无人消费，永远不会到达
           _pending_queues 中的 queue。

        修复：
        - process_direct: 创建 pending_queue 并注册到 _pending_queues
        - _announce_result: 在发布到 bus 的同时，直接将消息放入对应的
          pending_queue（绕过未运行的消息总线消费器）
        """
        import nanobot.agent.loop as _loop_mod
        import nanobot.agent.subagent as _subagent_mod

        # --- Patch 1: process_direct 创建 pending_queue ---
        _orig_process_direct = _loop_mod.AgentLoop.process_direct

        async def _process_direct_with_pending(
            self: _loop_mod.AgentLoop,
            content: str,
            session_key: str = "cli:direct",
            channel: str = "cli",
            chat_id: str = "direct",
            media: list[str] | None = None,
            on_progress: Any | None = None,
            on_stream: Any | None = None,
            on_stream_end: Any | None = None,
        ) -> Any:
            await self._connect_mcp()
            msg = _loop_mod.InboundMessage(
                channel=channel, sender_id="user", chat_id=chat_id,
                content=content, media=media or [],
            )
            lock = self._session_locks.setdefault(session_key, asyncio.Lock())
            pending: asyncio.Queue | None = None
            try:
                async with lock:
                    pending = asyncio.Queue(maxsize=20)
                    self._pending_queues[session_key] = pending
                    result = await self._process_message(
                        msg,
                        session_key=session_key,
                        on_progress=on_progress,
                        on_stream=on_stream,
                        on_stream_end=on_stream_end,
                        pending_queue=pending,
                    )
                    return result
            finally:
                if self._pending_queues.get(session_key) is pending:
                    self._pending_queues.pop(session_key, None)
                if pending is not None:
                    while True:
                        try:
                            item = pending.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                        await self.bus.publish_inbound(item)
                if channel == "websocket":
                    await self._webui_turns.publish_run_status(msg, "idle")
                    self._pending_turn_latency_ms.pop(session_key, None)
                    self._webui_turns.discard(session_key)

        _loop_mod.AgentLoop.process_direct = _process_direct_with_pending

        # --- Patch 2: _announce_result 直接放入 pending_queue ---
        _orig_announce = _subagent_mod.SubagentManager._announce_result

        async def _announce_result_direct(
            self: _subagent_mod.SubagentManager,
            task_id: str,
            label: str,
            task: str,
            result: str,
            origin: dict[str, str],
            status: str,
            origin_message_id: str | None = None,
        ) -> None:
            await _orig_announce(
                self, task_id, label, task, result, origin, status,
                origin_message_id,
            )
            session_key = origin.get("session_key")
            if not session_key:
                return
            loop = getattr(self, "_loop", None)
            if loop is None:
                return
            pending_queue = loop._pending_queues.get(session_key)
            if pending_queue is None:
                return

            override = session_key
            announce_msg = _loop_mod.InboundMessage(
                channel="system",
                sender_id="subagent",
                chat_id=f"{origin.get('channel', 'cli')}:{origin.get('chat_id', 'direct')}",
                content=f"[Subagent {label} {status}]\n{result}",
                session_key_override=override,
                metadata={
                    "injected_event": "subagent_result",
                    "subagent_task_id": task_id,
                },
            )
            try:
                pending_queue.put_nowait(announce_msg)
                logger.info(
                    "Subagent [%s] result directly injected to pending_queue "
                    "for session %s",
                    task_id,
                    session_key,
                )
            except asyncio.QueueFull:
                logger.warning(
                    "Pending queue full for session %s, subagent [%s] result "
                    "will be consumed via bus",
                    session_key,
                    task_id,
                )

        _subagent_mod.SubagentManager._announce_result = _announce_result_direct

        logger.info(
            "Patched process_direct (pending queue) + _announce_result (direct injection)",
        )
