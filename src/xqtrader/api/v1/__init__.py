"""API v1 路由聚合。"""

from fastapi import APIRouter

from framework.config.settings import settings
from xqtrader.api.v1.health import router as health_router
from xqtrader.api.v1.security import router as security_router

router = APIRouter(prefix=settings.APP.API_PREFIX)

router.include_router(health_router)
router.include_router(security_router)
