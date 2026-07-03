"""将 Nanobot 生命周期事件写入 Redis Stream。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from nanobot.agent.hook import AgentHook, AgentHookContext

from agent.protocol import EventType
from agent.redis_bus import AgentRedisBus
from framework.commons.logger import get_logger
from xqtrader.domain.agent.services.memory_service import MemoryService

logger = get_logger("AGENT_MEMORY_HOOK")


class ContextInjectHook(AgentHook):
    """页面上下文注入 — 首轮迭代前把业务上下文作为临时 system 提示注入，不污染持久化的用户消息。

    注入到 context.messages（内存态），框架落盘的仍是原始用户消息，因此历史回载时不含上下文前缀。
    """

    def __init__(self, context: dict[str, Any] | None) -> None:
        super().__init__()
        self._context = context or {}
        self._injected = False

    def _build_note(self) -> str | None:
        parts: list[str] = []
        stock_symbol = self._context.get("stock_symbol")
        if stock_symbol:
            parts.append(f"用户当前正在查看股票: {stock_symbol}")
        page_source = self._context.get("page_source")
        if page_source:
            parts.append(f"页面来源: {page_source}")
        if not parts:
            return None
        return "[上下文]\n" + "\n".join(parts)

    async def before_iteration(self, context: AgentHookContext) -> None:
        if self._injected:
            return
        self._injected = True
        note_text = self._build_note()
        if not note_text:
            return
        note = {"role": "system", "content": note_text}
        insert_at = len(context.messages)
        for i in range(len(context.messages) - 1, -1, -1):
            if context.messages[i].get("role") == "user":
                insert_at = i
                break
        context.messages.insert(insert_at, note)


class MemoryRecallHook(AgentHook):
    """语义经验召回 — 首轮迭代前自动检索 Qdrant 并注入上下文；对话结束自动 index。

    按 run 构造（携带本 run 的 symbol / user_message），因 AgentHookContext
    不含 session_key/symbol，故不能用进程级单例。
    """

    def __init__(self, symbol: str | None, query: str) -> None:
        super().__init__()
        self._symbol = symbol
        self._query = query
        self._injected = False

    async def before_iteration(self, context: AgentHookContext) -> None:
        if self._injected:
            return
        self._injected = True
        try:
            results = await asyncio.to_thread(
                MemoryService.get_instance().search_memory,
                query=self._query,
                top_k=3,
                symbol=self._symbol,
            )
        except Exception:
            logger.warning("语义召回失败，跳过注入", exc_info=True)
            return
        if not results:
            return
        recall = "\n".join(
            f"- {r['text']}（相似度 {r['score']:.2f}）" for r in results if r.get("text")
        )
        if not recall:
            return
        note = {
            "role": "system",
            "content": f"[经验参考（非权威事实，仅供类比）]\n{recall}",
        }
        # 注入到最后一条用户消息之前，保证当前问题仍是最新上下文。
        insert_at = len(context.messages)
        for i in range(len(context.messages) - 1, -1, -1):
            if context.messages[i].get("role") == "user":
                insert_at = i
                break
        context.messages.insert(insert_at, note)
        logger.info("已注入 %d 条经验召回 (symbol=%s)", len(results), self._symbol)

    def finalize_content(self, context: AgentHookContext, content: str | None) -> str | None:
        if content and content.strip():
            text = content.strip()
            try:
                loop = asyncio.get_running_loop()
                loop.run_in_executor(None, self._index_safely, text)
            except RuntimeError:
                self._index_safely(text)
            except Exception:
                logger.warning("对话结论 index 调度失败", exc_info=True)
        return content

    def _index_safely(self, text: str) -> None:
        try:
            MemoryService.get_instance().index_memory(
                text=text,
                payload={"symbol": self._symbol, "role": "assistant"},
            )
        except Exception:
            logger.warning("对话结论 index 失败", exc_info=True)


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
            if _is_spawn(tc.name):
                await self._bus.publish_event(
                    EventType.SUBAGENT_START,
                    self._run_id,
                    session_id=self._session_id,
                    payload={
                        "task_id": str(getattr(tc, "id", "") or ""),
                        "label": _spawn_label(tc.arguments),
                        "task": _spawn_task(tc.arguments),
                    },
                )
                continue
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
            if _is_spawn(name):
                await self._bus.publish_event(
                    EventType.SUBAGENT_END,
                    self._run_id,
                    session_id=self._session_id,
                    payload={
                        "task_id": call_id,
                        "label": _spawn_label(
                            context.tool_calls[idx].arguments
                            if idx < len(context.tool_calls)
                            else {}
                        ),
                        "status": status,
                        "result_summary": str(detail)[:500] if detail else "",
                    },
                )
                continue
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


def _is_spawn(name: str) -> bool:
    return name == "spawn" or name.endswith("_spawn")


def _spawn_label(arguments: Any) -> str:
    args = arguments if isinstance(arguments, dict) else {}
    label = str(args.get("label") or "").strip()
    if label:
        return label
    task = str(args.get("task") or "").strip()
    return task[:30] + ("…" if len(task) > 30 else "") if task else "子任务"


def _spawn_task(arguments: Any) -> str:
    args = arguments if isinstance(arguments, dict) else {}
    return str(args.get("task") or "")[:500]


def _safe_args(arguments: Any) -> str:
    if isinstance(arguments, dict):
        text = json.dumps(arguments, ensure_ascii=False)
        return text[:500]
    return str(arguments)[:500]


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
