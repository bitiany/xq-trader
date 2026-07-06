"""投资者画像 API — 全局投资偏好

业务域：仓位风格、自选股等用户配置，供投研 Skill 读取。
"""

from fastapi import APIRouter

from xqtrader.domain.agent.models.preference import AgentPreference

router = APIRouter(prefix="/investor-profile", tags=["投资者画像"])


@router.get("", summary="读取全局投资偏好", operation_id="get_preference")
async def get_preference() -> dict:
    """读取全局投资偏好（单用户本地部署，id 恒为 1）"""
    pref = await AgentPreference.get_or_none(id=1)
    return pref.to_dict() if pref else {}
