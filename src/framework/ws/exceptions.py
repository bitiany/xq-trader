"""WebSocket领域异常层级"""

from __future__ import annotations


class WsError(Exception):
    """WebSocket基础异常"""


class WsConnectionError(WsError):
    """WebSocket连接异常"""


class WsMessageError(WsError):
    """WebSocket消息解析/处理异常"""


class WsPublishError(WsError):
    """WebSocket消息发布异常"""


class WsTicketError(WsError):
    """Ticket认证异常"""


class WsSpiError(WsError):
    """SPI执行异常"""
