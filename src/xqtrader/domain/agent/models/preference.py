"""Agent 全局偏好 — 单用户本地部署，单行配置

设计原则:
  - 单行表（id 恒为 1），存放风险偏好/自选股/交易风格等全局配置
  - Agent 启动时读取注入 context，用户可随时修改
"""

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase


class AgentPreference(AuditedBase):
    """Agent 全局偏好设置（单行表，id 恒为 1）"""

    __bind_key__ = "default"
    __tablename__ = "ag_preference"

    risk_appetite: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="风险偏好: 保守/稳健/激进",
    )
    watchlist: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, comment="自选股列表",
    )
    preferences: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="其他偏好设置",
    )
