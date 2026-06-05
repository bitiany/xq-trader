"""认证中间件 — API Key 校验。"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

OPEN_PATHS = {"/docs", "/redoc", "/openapi.json", "/health"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if path in OPEN_PATHS:
            return await call_next(request)

        return await call_next(request)
