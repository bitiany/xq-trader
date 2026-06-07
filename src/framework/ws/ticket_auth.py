"""Ticket认证器"""

from __future__ import annotations

import secrets
import time

from framework.commons.logger import get_logger
from framework.commons.redis_client import redis_client
from framework.ws.exceptions import WsTicketError
from framework.ws.messages import TICKET_PREFIX

logger = get_logger("ws.ticket")

TICKET_EXPIRE_SECONDS = 300


class TicketAuth:
    """Ticket认证器 — 一次性短令牌"""

    @staticmethod
    def generate(user_id: str = "anonymous") -> str:
        """生成一次性Ticket"""
        ticket = secrets.token_urlsafe(32)
        data = f"{user_id}:{time.time()}"
        redis_client.set(f"{TICKET_PREFIX}{ticket}", data, ex=TICKET_EXPIRE_SECONDS)
        logger.debug(f"Generated ticket for {user_id}")
        return ticket

    @staticmethod
    def validate(ticket: str) -> str | None:
        """验证Ticket，返回user_id或None。验证后删除（一次性使用）"""
        if not ticket:
            return None

        key = f"{TICKET_PREFIX}{ticket}"
        data = redis_client.get(key)
        if not data:
            return None

        # 删除已使用的ticket
        redis_client.delete(key)

        try:
            parts = str(data).split(":")
            user_id = parts[0] if parts else "anonymous"
            logger.debug(f"Ticket validated for {user_id}")
            return user_id
        except WsTicketError:
            raise
        except Exception as e:
            raise WsTicketError("Failed to parse ticket") from e


ticket_auth = TicketAuth()
