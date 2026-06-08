"""P1 验收脚本：注册表同步 + 样本池初始化 + 验证。

建表和 TimescaleDB 由服务启动时自动完成，此脚本仅做数据初始化。
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    from framework.dal.datasource_loader import DatasourceLoader
    from framework.dal.register import register_datasource_sync
    from framework.config.settings import settings

    # 初始化数据源
    loader = DatasourceLoader(settings.APP.DB_CONFIG_PATH)
    register_datasource_sync(loader.datasources)
    logger.info("数据源初始化完成")

    # 注册表同步
    from xqtrader.domain.factor.services.registry_sync import FactorRegistrySyncer
    result = await FactorRegistrySyncer.sync_all()
    logger.info("注册表同步结果: %s", result)

    # 样本池初始化
    from xqtrader.domain.factor.services.pool_initializer import FactorPoolInitializer
    pool_result = await FactorPoolInitializer.init_pools()
    logger.info("样本池初始化结果: %s", pool_result)

    # 验证
    from xqtrader.domain.factor.models import FacFactorRegistry, FacFactorPool
    count = await FacFactorRegistry.count()
    logger.info("fac_factor_registry 行数: %d", count)

    pool_count = await FacFactorPool.count()
    logger.info("fac_factor_pool 行数: %d", pool_count)

    logger.info("P1 验收完成")


if __name__ == "__main__":
    asyncio.run(main())
