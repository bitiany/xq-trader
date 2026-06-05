"""统一响应中间件 — 业务层直接返回数据，中间件自动包装为 ResponseModel。"""

import json
from collections.abc import AsyncIterator

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from framework.middleware.response_schema import ResponseModel

_SKIP_PATHS = {"/docs", "/redoc", "/openapi.json", "/health"}


def _is_response_model(data: dict) -> bool:
    return isinstance(data, dict) and "code" in data and "message" in data and "data" in data


class ResponseMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        if path in _SKIP_PATHS or path.startswith("/ws"):
            return await call_next(request)

        response = await call_next(request)

        if response.status_code >= 400:
            return response

        if response.headers.get("Content-Type") != "application/json":
            return response

        body = b""
        body_iterator: AsyncIterator[bytes] | None = getattr(response, "body_iterator", None)
        if body_iterator is None:
            return response
        async for chunk in body_iterator:
            body += chunk

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return response

        if _is_response_model(data):
            headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
            return JSONResponse(content=data, status_code=response.status_code, headers=headers)

        wrapped = ResponseModel(code=0, message="success", data=data)
        headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        return JSONResponse(content=wrapped.model_dump(), status_code=response.status_code, headers=headers)
