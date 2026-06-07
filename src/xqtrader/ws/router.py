"""WebSocket路由与Ticket API"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket
from pydantic import BaseModel

from framework.ws.ticket_auth import TICKET_EXPIRE_SECONDS, ticket_auth

from .handler import ws_handler

ws_router = APIRouter()


@ws_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_handler.handle(websocket)


# Ticket API
ticket_router = APIRouter(prefix="/api/v1/ws", tags=["websocket"])


class TicketResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: dict


@ticket_router.post("/ticket", response_model=TicketResponse)
async def create_ticket():
    """生成WebSocket连接Ticket"""
    ticket = ticket_auth.generate()
    return TicketResponse(data={"ticket": ticket, "expires_in": TICKET_EXPIRE_SECONDS})
