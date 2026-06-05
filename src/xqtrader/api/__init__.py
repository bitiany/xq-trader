"""API 路由聚合入口。"""

from fastapi import APIRouter

from xqtrader.api.v1 import router as v1_router

router = APIRouter()

router.include_router(v1_router)
