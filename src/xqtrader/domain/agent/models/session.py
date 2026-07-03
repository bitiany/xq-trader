"""Agent 会话与消息 — nanobot 框架会话记忆的 PostgreSQL 后端存储

设计原则:
  - 承接 nanobot 框架原生 Session 语义（由 PgSessionManager 读写），
    替代框架默认的 jsonl 文件存储；框架自动加载历史、注入上下文、每轮落盘。
  - session_key 直接按标的: stock:{symbol} / general:{id} / general
  - message 用单个 payload JSONB 完整存储原始 nanobot message dict，无损保留
    role/content/timestamp/tool_calls/reasoning_content/thinking_blocks/media 等全部字段。
  - session 与 message 间无物理外键，仅逻辑关联（项目规范）。
"""

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base


class AgentSession(Base):
    """Agent 会话元数据 — 对应 nanobot Session 的头部信息"""

    __bind_key__ = "default"
    __tablename__ = "ag_session"

    session_key: Mapped[str] = mapped_column(
        String(128), primary_key=True,
        comment="nanobot session key: stock:{symbol} / general:{id} / general",
    )
    meta: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="nanobot Session.metadata（含 title 等）",
    )
    last_consolidated: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="已整合到长期记忆的消息游标",
    )
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(),
    )


class AgentMessage(Base):
    """Agent 会话消息 — 完整历史持久化，payload 无损保留 nanobot message dict"""

    __bind_key__ = "default"
    __tablename__ = "ag_message"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True,
    )
    session_key: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True, comment="逻辑关联 ag_session.session_key",
    )
    seq: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="会话内序号（与 Session.messages 列表顺序一致）",
    )
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="完整 nanobot message dict",
    )
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
