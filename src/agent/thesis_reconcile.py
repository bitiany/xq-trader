"""论点卡过期治理后台任务 — Worker 进程内定时执行。"""

from __future__ import annotations

import asyncio

from agent.config import agent_settings
from framework.commons.logger import get_logger
from xqtrader.domain.agent.services.thesis_service import ThesisService

logger = get_logger("AGENT_THESIS_RECONCILE")

_task: asyncio.Task[None] | None = None


async def _reconcile_loop() -> None:
    service = ThesisService()
    interval = agent_settings.THESIS_RECONCILE_INTERVAL_S
    while True:
        try:
            await service.reconcile_all_expired()
        except Exception:
            logger.exception("论点卡过期治理任务失败")
        await asyncio.sleep(interval)


def start_thesis_reconcile_task() -> asyncio.Task[None]:
    """启动论点卡过期治理循环（Worker 启动时调用一次）。"""
    global _task
    if _task is not None and not _task.done():
        return _task
    _task = asyncio.create_task(_reconcile_loop(), name="thesis-reconcile")
    logger.info(
        "论点卡过期治理任务已启动 interval=%ss",
        agent_settings.THESIS_RECONCILE_INTERVAL_S,
    )
    return _task


async def stop_thesis_reconcile_task() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
