"""投资者偏好服务 — 单行表读写

设计原则:
  - 单行表（id 恒为 1），无新增/删除，仅 upsert
  - 其他字段（risk_appetite/watchlist/preferences）整体替换
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from framework.commons.logger import get_logger
from framework.dal.transaction.transactional import transactional
from xqtrader.domain.agent.models.preference import AgentPreference

logger = get_logger("AGENT.PREFERENCE")


class InvestorProfileService:
    """投资者偏好读写服务（单行表，id 恒为 1）"""

    async def get_preference(self) -> dict[str, Any]:
        """读取全局投资偏好（不存在则返回空字典）"""
        pref = await AgentPreference.get_or_none(id=1)
        return pref.to_dict() if pref else {}

    @transactional(bind_key="default")
    async def update_preference(
        self,
        *,
        risk_appetite: str | None = None,
        watchlist: list[str] | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """更新全局投资偏好（仅传入的字段被更新，未传字段保持不变）

        Args:
            risk_appetite: 风险偏好 保守/稳健/激进（None 表示不更新）
            watchlist: 自选股列表（None 表示不更新）
            preferences: 其他偏好设置（None 表示不更新）

        Returns:
            更新后的偏好字典
        """
        pref = await AgentPreference.get_or_none(id=1)

        if pref is None:
            pref = await AgentPreference.create(
                id=1,
                risk_appetite=risk_appetite,
                watchlist=watchlist,
                preferences=preferences,
            )
            logger.info("投资者偏好初始化创建: id=1")
            return pref.to_dict()

        update_data: dict[str, Any] = {}
        update_fields: list[str] = []

        if risk_appetite is not None:
            update_data["risk_appetite"] = risk_appetite
            update_fields.append("risk_appetite")

        if watchlist is not None:
            update_data["watchlist"] = watchlist
            update_fields.append("watchlist")

        if preferences is not None:
            update_data["preferences"] = preferences
            update_fields.append("preferences")

        if not update_data:
            return pref.to_dict()

        # updated_at 必须显式更新，保证审计轨迹（update_by 不触发 ORM onupdate）
        update_data["updated_at"] = datetime.now(timezone.utc)
        await AgentPreference.update_by(update_data, id=1)
        refreshed = await AgentPreference.get_or_none(id=1)
        logger.info(
            "投资者偏好已更新: fields=%s",
            update_fields,
        )
        return refreshed.to_dict() if refreshed else {}
