"""API v1 路由聚合。"""

from fastapi import APIRouter

from framework.config.settings import settings
from xqtrader.api.v1.agent.agent import router as agent_router
from xqtrader.api.v1.backtest import router as backtest_router
from xqtrader.api.v1.broker import router as broker_router
from xqtrader.api.v1.data import router as data_router
from xqtrader.api.v1.factors import router as factors_router
from xqtrader.api.v1.health import router as health_router
from xqtrader.api.v1.rules import router as rules_router
from xqtrader.api.v1.scheduler import router as scheduler_router
from xqtrader.api.v1.security import router as security_router
from xqtrader.api.v1.selection import router as selection_router
from xqtrader.api.v1.stocks import router as stocks_router
from xqtrader.api.v1.strategies import router as strategies_router
from xqtrader.api.v1.trading import router as trading_router
from xqtrader.api.v1.universe import router as universe_router
from xqtrader.api.v1.watermark import router as watermark_router
from xqtrader.api.v1.workflow import router as workflow_router

router = APIRouter(prefix=settings.APP.API_PREFIX)

router.include_router(health_router)
router.include_router(scheduler_router)
router.include_router(security_router)
router.include_router(watermark_router)
router.include_router(data_router)
router.include_router(broker_router)
router.include_router(workflow_router)
# 选股研究台
router.include_router(strategies_router)
router.include_router(rules_router)
router.include_router(factors_router)
router.include_router(universe_router)
router.include_router(selection_router)
router.include_router(backtest_router)
router.include_router(trading_router)
router.include_router(stocks_router)
# AI Agent
router.include_router(agent_router, prefix="/agent", tags=["agent"])
