"""Agent Worker — 消费 Redis 队列并执行 Nanobot。"""

from __future__ import annotations

import asyncio
import signal
import sys

from agent.brief_content import is_indexable_brief
from agent.config import agent_settings
from agent.governance_hooks import OrchestratorToolPolicyHook, SpawnContractHook
from agent.hooks import (
    ContextInjectHook,
    MemoryRecallHook,
    RedisEventHook,
    RunCancelHook,
    ShortTermRecallHook,
)
from agent.protocol import EventType, RunStatus
from agent.redis_bus import AgentRedisBus
from agent.runtime import build_bot, get_nanobot_lock, init_runtime
from agent.schemas import RunTask
from agent.thesis_reconcile import start_thesis_reconcile_task, stop_thesis_reconcile_task
from agent.trace_context import RunTraceContext, clear_run_trace, set_run_trace, trace_fields
from framework.commons.logger import get_logger
from xqtrader.domain.agent.errors import RunCancelledError
from xqtrader.domain.agent.services.memory_service import MemoryService
from xqtrader.domain.agent.services.thesis_service import ThesisService

logger = get_logger("AGENT_WORKER")


class AgentWorker:
    def __init__(self) -> None:
        self._bus = AgentRedisBus()
        self._semaphore = asyncio.Semaphore(
            agent_settings.MAX_CONCURRENT_RUNS
        )
        self._running_tasks: set[asyncio.Task[None]] = set()
        self._shutdown = False
        self._initialized = False

    async def start(self) -> None:
        await self._bus.connect()
        if not self._initialized:
            init_runtime()
            try:
                reconciled = await ThesisService().reconcile_all_expired()
                if reconciled:
                    logger.info("启动时论点卡过期治理: affected=%d", reconciled)
            except Exception:
                logger.exception("启动时论点卡过期治理失败")
            start_thesis_reconcile_task()
            self._initialized = True
        logger.info(
            "Agent worker started: id=%s max_concurrent=%s",
            agent_settings.WORKER_ID,
            agent_settings.MAX_CONCURRENT_RUNS,
        )
        while not self._shutdown:
            task = await self._bus.dequeue_run(
                agent_settings.QUEUE_BLOCK_SECONDS
            )
            if task is None:
                continue
            job = asyncio.create_task(self._run_guarded(task))
            self._running_tasks.add(job)
            job.add_done_callback(self._running_tasks.discard)

    async def stop(self) -> None:
        self._shutdown = True
        await stop_thesis_reconcile_task()
        if self._running_tasks:
            await asyncio.gather(*self._running_tasks, return_exceptions=True)
        await self._bus.close()

    async def _run_guarded(self, task: RunTask) -> None:
        async with self._semaphore:
            await self._execute_run(task)

    async def _execute_run(self, task: RunTask) -> None:
        run_id = task.run_id
        session_id = task.session_id
        if await self._bus.is_cancelled(run_id):
            await self._bus.set_run_status(run_id, RunStatus.CANCELLED)
            await self._bus.publish_event(
                EventType.DONE,
                run_id,
                session_id=session_id,
                payload={"status": RunStatus.CANCELLED.value},
            )
            return

        await self._bus.set_run_status(run_id, RunStatus.RUNNING)
        await self._bus.publish_event(
            EventType.RUN_START,
            run_id,
            session_id=session_id,
            payload={"message": task.message[:200]},
        )

        hook = RedisEventHook(
            self._bus,
            run_id,
            session_id,
            trace_id=task.trace_id,
        )
        set_run_trace(RunTraceContext(run_id=run_id, trace_id=task.trace_id))
        trace_suffix = f" trace_id={task.trace_id}" if task.trace_id else ""
        try:
            async with get_nanobot_lock():
                bot = build_bot(model=task.model)
                session_key = self._build_session_key(task)
                symbol = (task.context or {}).get("stock_symbol")
                context_hook = ContextInjectHook(task.context)
                recall_hook = MemoryRecallHook(symbol=symbol, query=task.message)
                short_term_hook = ShortTermRecallHook(session_key=session_key, symbol=symbol)
                cancel_hook = RunCancelHook(self._bus, run_id)
                policy_hook = OrchestratorToolPolicyHook(task.context)
                spawn_hook = SpawnContractHook(task.context)
                result = await bot.run(
                    task.message,
                    session_key=session_key,
                    hooks=[
                        hook,
                        context_hook,
                        recall_hook,
                        short_term_hook,
                        cancel_hook,
                        policy_hook,
                        spawn_hook,
                    ],
                )
                if await self._bus.is_cancelled(run_id):
                    status = RunStatus.CANCELLED
                else:
                    status = RunStatus.COMPLETED
                    content = (result.content or "").strip()
                    await self._bus.publish_event(
                        EventType.MESSAGE,
                        run_id,
                        session_id=session_id,
                        payload={"content": result.content},
                    )
                    if content and is_indexable_brief(content):
                        try:
                            await asyncio.to_thread(
                                MemoryService.get_instance().index_memory,
                                content,
                                {"symbol": symbol, "role": "assistant", "type": "brief"},
                            )
                        except Exception:
                            logger.error(
                                "对话结论 Qdrant 索引失败 run_id=%s%s",
                                run_id,
                                trace_suffix,
                                exc_info=True,
                            )
                    elif content:
                        logger.info(
                            "跳过 Qdrant 索引：内容未达简报门槛 run_id=%s chars=%d",
                            run_id,
                            len(content),
                        )
            await self._bus.set_run_status(run_id, status)
            await self._bus.publish_event(
                EventType.DONE,
                run_id,
                session_id=session_id,
                payload={"status": status.value},
            )
            logger.info("Run completed: run_id=%s status=%s%s", run_id, status.value, trace_suffix)
        except RunCancelledError:
            await self._bus.set_run_status(run_id, RunStatus.CANCELLED)
            await self._bus.publish_event(
                EventType.DONE,
                run_id,
                session_id=session_id,
                payload={"status": RunStatus.CANCELLED.value},
            )
            logger.info("Run cancelled: run_id=%s%s", run_id, trace_suffix)
        except Exception as exc:
            logger.exception(
                "Run failed: run_id=%s%s",
                run_id,
                trace_suffix,
                extra=trace_fields(),
            )
            try:
                await self._bus.set_run_status(
                    run_id,
                    RunStatus.FAILED,
                    error=str(exc),
                )
                await self._bus.publish_event(
                    EventType.ERROR,
                    run_id,
                    session_id=session_id,
                    payload={"message": str(exc)},
                )
                await self._bus.publish_event(
                    EventType.DONE,
                    run_id,
                    session_id=session_id,
                    payload={"status": RunStatus.FAILED.value},
                )
            except Exception:
                logger.exception(
                    "Failed to publish failure event for run_id=%s",
                    run_id,
                    exc_info=True,
                )
        finally:
            clear_run_trace()

    @staticmethod
    def _build_session_key(task: RunTask) -> str:
        """会话隔离 key 由业务侧在创建会话时决定，Agent 层仅透传，不推导业务语义。"""
        return task.session_key or f"session:{task.session_id}"


async def _async_main() -> None:
    worker = AgentWorker()
    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        asyncio.create_task(worker.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    try:
        await worker.start()
    finally:
        await worker.stop()


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
