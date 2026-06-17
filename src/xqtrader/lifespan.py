from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from framework.commons.logger import get_logger
from xqtrader.ws.scheduler import WsTopicScheduler

# 导入领域模型，确保 ORM 子类注册到 Base.metadata，create_tables 时可发现
import xqtrader.domain.factor.models  # noqa: F401
import xqtrader.domain.trading.models  # noqa: F401

logger = get_logger("LIFESPAN")


@asynccontextmanager
async def app_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("应用启动中...")
    WsTopicScheduler.start()
    yield
    WsTopicScheduler.stop()
    logger.info("应用已关闭")
