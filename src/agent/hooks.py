"""将 Nanobot 生命周期事件写入 Redis Stream。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nanobot.agent.hook import AgentHook, AgentHookContext

from agent.protocol import EventType
from agent.redis_bus import AgentRedisBus


class RedisEventHook(AgentHook):
    """发布工具与 token 事件供 API SSE 转发。"""

    def __init__(
        self,
        bus: AgentRedisBus,
        run_id: str,
        session_id: str,
    ) -> None:
        super().__init__()
        self._bus = bus
        self._run_id = run_id
        self._session_id = session_id

    def wants_streaming(self) -> bool:
        return True

    async def on_stream(self, context: AgentHookContext, delta: str) -> None:
        if not delta:
            return
        await self._bus.publish_event(
            EventType.TOKEN,
            self._run_id,
            session_id=self._session_id,
            payload={"delta": delta},
        )

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        for tc in context.tool_calls:
            await self._bus.publish_event(
                EventType.TOOL_START,
                self._run_id,
                session_id=self._session_id,
                payload={
                    "call_id": str(getattr(tc, "id", "") or ""),
                    "name": tc.name,
                    "arguments": _safe_args(tc.arguments),
                    "summary": _tool_start_summary(tc.name, tc.arguments),
                },
            )

    async def after_iteration(self, context: AgentHookContext) -> None:
        for idx, ev in enumerate(context.tool_events):
            name = ev.get("name", "tool")
            status = ev.get("status", "ok")
            detail = ev.get("detail") or ev.get("result") or ""
            call_id = ""
            if idx < len(context.tool_calls):
                call_id = str(getattr(context.tool_calls[idx], "id", "") or "")
            await self._bus.publish_event(
                EventType.TOOL_END,
                self._run_id,
                session_id=self._session_id,
                payload={
                    "call_id": call_id,
                    "name": name,
                    "status": status,
                    "detail": str(detail)[:1000] if detail else "",
                    "summary": _tool_end_summary(name, detail, status),
                },
            )


def _safe_args(arguments: Any) -> Any:
    if isinstance(arguments, dict):
        text = json.dumps(arguments, ensure_ascii=False)
        return text[:500] if len(text) > 500 else arguments
    text = str(arguments)
    return text[:500]


def _basename(path: str) -> str:
    try:
        return Path(path).name or path
    except (TypeError, ValueError):
        return path


def _tool_start_summary(name: str, arguments: Any) -> str:
    args = arguments if isinstance(arguments, dict) else {}
    if name in ("write_file", "edit_file"):
        return _basename(str(args.get("path", "")))
    if name == "notebook_edit":
        return _basename(str(args.get("notebook_path", args.get("path", ""))))
    if name == "read_file":
        return _basename(str(args.get("path", "")))
    if name == "list_dir":
        return _basename(str(args.get("path", args.get("directory", "."))))
    if name == "grep":
        pattern = str(args.get("pattern", ""))[:40]
        return pattern or name
    if name == "complete_goal":
        return ""
    return name


def _tool_end_summary(name: str, detail: Any, status: str) -> str:
    if status == "error":
        text = str(detail).strip()
        return text[:120] if text else "failed"
    if name == "complete_goal":
        return "done"
    text = str(detail).strip()
    if not text:
        return "ok"
    if "Successfully" in text or "success" in text.lower():
        for token in text.split():
            if token.endswith((".py", ".ipynb", ".md", ".json", ".txt")):
                return _basename(token.strip("\\/"))
        return text[:80]
    return text[:80]
