"""访问日志中间件 — 记录请求方法、路径、状态码、耗时、request_id。"""

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from framework.commons.logger import RequestContextLogger, get_logger

_logger = get_logger("ACCESS")


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        log = RequestContextLogger(_logger, request_id)

        start_time = time.perf_counter()

        log.info("%s %s", request.method, request.url.path)

        response = await call_next(request)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        log.info(
            "%s %s status=%d elapsed=%.2fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{elapsed_ms:.2f}ms"
        return response
