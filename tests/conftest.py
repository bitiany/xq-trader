"""
Pytest 配置文件

统一处理测试环境初始化：
- sys.path 配置（src 目录）
- 数据源 fixture（FastAPI + register_datasource）
- API 集成测试 client fixture
"""
import sys
from pathlib import Path

import pytest_asyncio

# ==================== sys.path 配置 ====================
SRC_DIR = str(Path(__file__).parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# 将 tests/ 目录加入 sys.path，使 tests.backtest.xxx 模块路径可被解析
_TESTS_DIR = Path(__file__).parent
_TESTS_DIR_STR = str(_TESTS_DIR)
if _TESTS_DIR_STR not in sys.path:
    sys.path.insert(0, _TESTS_DIR_STR)


# ==================== 公共 Fixture ====================
@pytest_asyncio.fixture(scope="session")
def event_loop():
    """创建 session 级别的事件循环"""
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def app_with_datasource():
    """
    创建集成数据源的 FastAPI 应用实例（session 级别复用）

    使用 register_datasource 方式初始化，与生产环境保持一致。
    环境变量通过 .env 文件或系统环境变量提供，不做任何绕过。
    """
    from fastapi import FastAPI

    from framework.config.settings import settings
    from framework.dal.datasource_loader import DatasourceLoader
    from framework.dal.register import register_datasource

    loader = DatasourceLoader(config_path=settings.APP.DB_CONFIG_PATH)

    app = FastAPI()

    register_datasource(
        app,
        datasource_config=loader.datasources,
        generate_schema=True,
        timescale_config=loader.timescale_config,
    )

    lifespan = app.router.lifespan_context(app)
    async with lifespan:
        yield app


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def api_client():
    """
    REST API 集成测试客户端（session 级别复用）

    使用 httpx ASGITransport 直接连接 FastAPI 应用，
    无需启动真实 HTTP 服务器，测试速度更快且稳定。
    通过完整应用栈（中间件 + 异常处理 + 路由 + 数据源）验证接口行为。
    手动触发 lifespan 以初始化数据源。
    """
    import httpx

    from xqtrader.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


def pytest_configure(config):
    """Pytest 配置钩子"""
    config.addinivalue_line(
        "markers", "asyncio: mark test as an async test"
    )
