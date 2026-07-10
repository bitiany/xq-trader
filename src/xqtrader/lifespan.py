import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import xqtrader.domain.agent.models  # noqa: F401
import xqtrader.domain.factor.models  # noqa: F401
import xqtrader.domain.market.models.candlestick  # noqa: F401
import xqtrader.domain.trading.models  # noqa: F401
from framework.commons.logger import get_logger
from xqtrader.ws.scheduler import WsTopicScheduler

logger = get_logger("LIFESPAN")


async def _auto_connect_qmt() -> None:
    """应用启动时自动连接 QMT 交易服务并订阅账号。"""
    from framework.config.settings import settings

    qmt = settings.QMT
    if not qmt.QMT_USERDATA_PATH:
        logger.info("QMT_USERDATA_PATH 未配置，跳过自动连接")
        return

    from xqtrader.broker.services.qmt_callback_handler import QmtCallbackHandler
    from xqtrader.broker.services.qmt_connection import QmtConnection
    from xqtrader.broker.services.qmt_trader import QmtTrader

    connection = QmtConnection.get_instance()
    result = await connection.connect_async()
    if result == 0:
        main_loop = asyncio.get_running_loop()
        callback_handler = QmtCallbackHandler.get_instance(main_loop=main_loop)
        connection.trader.register_callback(callback_handler)
        trader = QmtTrader()
        await trader.subscribe_account()
        logger.info("QMT 交易服务自动连接成功")
    else:
        logger.warning("QMT 交易服务自动连接失败: result=%s", result)


@asynccontextmanager
async def app_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("应用启动中...")
    WsTopicScheduler.start()

    # 注册 on_demand 因子计算 + SPI 插件到统一注册中心
    # （trading 层向 factor 层 OnDemandComputeRegistry 注入默认实现，依赖反转）
    from xqtrader.domain.trading.backtest.on_demand_registration import (
        register_default_on_demand_computes,
    )

    register_default_on_demand_computes()

    # 自动连接 QMT 交易服务
    await _auto_connect_qmt()

    # 启动盘内监控后台任务（监听 Redis intraday.control 控制信号）
    from xqtrader.domain.market.intraday.intraday_monitor_task import IntradayMonitorTask

    intraday_task = IntradayMonitorTask.get_instance()
    await intraday_task.start()

    yield
    WsTopicScheduler.stop()

    # 停止盘内监控
    await intraday_task.stop()
    # 关闭 Agent Redis 连接
    from xqtrader.api.v1.agent.agent import _service

    await _service._bus.close()
    logger.info("应用已关闭")
