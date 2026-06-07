"""WebSocket连接处理器"""

from __future__ import annotations

from fastapi import WebSocket, WebSocketDisconnect

from framework.commons.logger import get_logger
from framework.ws.connection_manager import connection_manager
from framework.ws.exceptions import WsConnectionError, WsMessageError
from framework.ws.messages import WsServerMessage, WsServerMessageType
from framework.ws.ticket_auth import ticket_auth

logger = get_logger("ws.handler")


class WsHandler:
    """WebSocket连接处理器"""

    @staticmethod
    async def handle(websocket: WebSocket) -> None:
        """WebSocket连接处理主入口"""
        await connection_manager.start_heartbeat()

        conn_id = await connection_manager.connect(websocket)

        try:
            # 从URL参数自动认证
            ticket = websocket.query_params.get("ticket", "")
            if ticket:
                user_id = ticket_auth.validate(ticket)
                if user_id:
                    await connection_manager.send(
                        conn_id,
                        WsServerMessage(type=WsServerMessageType.ACK, data={"user_id": user_id}),
                    )
                    logger.info(f"Auto-authenticated {conn_id[:8]} as {user_id}")

            # 消息循环
            while True:
                data = await websocket.receive_text()
                await connection_manager.handle_message(conn_id, data)

        except WebSocketDisconnect:
            logger.info(f"Connection {conn_id[:8]} disconnected")
        except WsConnectionError as e:
            logger.error(f"Connection {conn_id[:8]} error: {e}")
        except WsMessageError as e:
            logger.error(f"Connection {conn_id[:8]} message error: {e}")
        except Exception as e:
            logger.error(f"Connection {conn_id[:8]} unexpected error: {e}")
        finally:
            await connection_manager.disconnect(conn_id)


ws_handler = WsHandler()
