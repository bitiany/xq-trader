"""投资者画像 API — 全局投资偏好

业务域：仓位风格、自选股等用户配置，供投研 Skill 读取。
"""

from typing import Any, cast

from fastapi import APIRouter
from pydantic import BaseModel, Field

from xqtrader.domain.agent.services.preference_service import InvestorProfileService

router = APIRouter(prefix="/investor-profile", tags=["投资者画像"])

_profile_service = InvestorProfileService()


class PreferenceUpdateRequest(BaseModel):
    """全局投资偏好更新请求（所有字段可选，未传字段保持不变）"""

    risk_appetite: str | None = Field(
        default=None, description="风险偏好: 保守/稳健/激进",
    )
    watchlist: list[str] | None = Field(default=None, description="自选股列表")
    preferences: dict[str, Any] | None = Field(default=None, description="其他偏好设置")


@router.get("", summary="读取全局投资偏好", operation_id="get_preference")
async def get_preference() -> dict:
    """读取全局投资偏好（单用户本地部署，id 恒为 1）"""
    return await _profile_service.get_preference()


@router.post("", summary="更新全局投资偏好", operation_id="update_preference")
async def update_preference(req: PreferenceUpdateRequest) -> dict:
    """更新全局投资偏好（仅传入字段被更新，未传字段保持不变）"""
    return cast("dict", await _profile_service.update_preference(
        risk_appetite=req.risk_appetite,
        watchlist=req.watchlist,
        preferences=req.preferences,
    ))
