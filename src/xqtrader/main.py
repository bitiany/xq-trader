import uvicorn
from fastapi import FastAPI

from framework.config.settings import settings
from framework.dal.datasource_loader import DatasourceLoader
from framework.dal.register import register_datasource
from framework.middleware import (
    AuthMiddleware,
    LoggingMiddleware,
    ResponseMiddleware,
    register_exception_handlers,
)
from xqtrader.api import router as api_router
from xqtrader.lifespan import app_lifespan
from xqtrader.ws import ticket_router, ws_router

# 确保新因子系统模型被 import，以便 DatasourceManager 自动发现并建表
import xqtrader.domain.factor.models  # noqa: F401


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP.TITLE,
        version=settings.APP.VERSION,
        description=settings.APP.DESCRIPTION,
        lifespan=app_lifespan,
    )

    app.add_middleware(ResponseMiddleware)
    app.add_middleware(AuthMiddleware)
    app.add_middleware(LoggingMiddleware)

    register_exception_handlers(app)

    loader = DatasourceLoader(settings.APP.DB_CONFIG_PATH)
    register_datasource(
        app,
        datasource_config=loader.datasources,
        generate_schema=settings.APP.GENERATE_SCHEMA_ON_START,
        timescale_config=loader.timescale_config,
    )

    app.include_router(api_router)
    app.include_router(ws_router)
    app.include_router(ticket_router)

    return app


def run() -> None:
    uvicorn.run(
        "xqtrader.main:create_app",
        host="0.0.0.0",
        port=settings.APP.PORT,
        factory=True,
    )


if __name__ == "__main__":
    run()
