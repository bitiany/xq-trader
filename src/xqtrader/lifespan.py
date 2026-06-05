from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from framework.commons.logger import get_logger

logger = get_logger("LIFESPAN")


@asynccontextmanager
async def app_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("应用启动中...")
    yield
    logger.info("应用已关闭")
