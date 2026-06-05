"""
Pytest 配置文件

统一处理测试环境初始化：
- sys.path 配置（src 目录）
- 数据源 fixture（FastAPI + register_datasource）
"""
import sys
from pathlib import Path

import pytest_asyncio

# ==================== sys.path 配置 ====================
SRC_DIR = str(Path(__file__).parent.parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# 自动发现 tests/ 下的所有子目录，加入 sys.path
# 用于导入各子目录下的 models 等模块
# 注意：不将 tests/ 本身加入 sys.path，避免 tests/framework 与 src/framework 包名冲突
_TESTS_DIR = Path(__file__).parent
for _subdir in _TESTS_DIR.iterdir():
    if _subdir.is_dir() and (_subdir / "__init__.py").exists() is False:
        _subdir_str = str(_subdir)
        if _subdir_str not in sys.path:
            sys.path.insert(0, _subdir_str)


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


def pytest_configure(config):
    """Pytest 配置钩子"""
    config.addinivalue_line(
        "markers", "asyncio: mark test as an async test"
    )
