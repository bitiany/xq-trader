from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import xqtrader.domain.factor.models  # noqa: F401
import xqtrader.domain.trading.models  # noqa: F401
from framework.commons.logger import get_logger
from xqtrader.ws.scheduler import WsTopicScheduler

logger = get_logger("LIFESPAN")


@asynccontextmanager
async def app_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("应用启动中...")
    WsTopicScheduler.start()
    yield
    WsTopicScheduler.stop()
    # 关闭 Agent Redis 连接
    from xqtrader.api.v1.agent.agent import _service

    await _service._bus.close()
    logger.info("应用已关闭")
