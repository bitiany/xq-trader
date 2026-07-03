"""Agent 薄 API 路由 — 仅入队与 SSE，不执行 AgentLoop。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from starlette.responses import JSONResponse

from xqtrader.domain.agent.schemas import (
    CreateSessionRequest,
    SessionHistoryResponse,
    SessionResponse,
    SubmitMessageRequest,
    SubmitMessageResponse,
)
from xqtrader.domain.agent.service import AgentService

router = APIRouter()
_service = AgentService()


@router.post("/sessions", response_model=SessionResponse, status_code=201)
async def create_session(
    request: Request,
    body: CreateSessionRequest,
) -> SessionResponse:
    return await _service.create_session(request, body)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    return await _service.get_session(session_id)


@router.get("/history", response_model=SessionHistoryResponse)
async def get_history(session_key: str) -> SessionHistoryResponse:
    return await _service.get_history(session_key)


@router.post(
    "/sessions/{session_id}/messages",
    response_model=SubmitMessageResponse,
    status_code=202,
)
async def submit_message(
    request: Request,
    session_id: str,
    body: SubmitMessageRequest,
) -> SubmitMessageResponse:
    return await _service.submit_message(request, session_id, body)


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> JSONResponse:
    result = await _service.get_run_status(run_id)
    return JSONResponse(content=result.model_dump())


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str) -> StreamingResponse:
    return StreamingResponse(
        _service.stream_run_events(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> JSONResponse:
    result = await _service.cancel_run(run_id)
    return JSONResponse(content=result.model_dump())
