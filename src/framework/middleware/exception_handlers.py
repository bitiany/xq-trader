"""统一异常处理器 — 通过 FastAPI exception_handler 机制捕获并格式化异常。"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from framework.commons.exceptions import BusinessException
from framework.commons.logger import get_logger
from framework.middleware.response_schema import ResponseModel

logger = get_logger("EXCEPTION")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BusinessException)
    async def business_exception_handler(request: Request, exc: BusinessException) -> JSONResponse:
        http_status = exc.code if 100 <= exc.code <= 599 else 400
        logger.warning("BusinessException: %s, code=%d, path=%s", exc.message, exc.code, request.url.path)
        return JSONResponse(
            status_code=http_status,
            content=ResponseModel(code=exc.code, message=exc.message, data=None).model_dump(),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict):
            message = exc.detail.get("message", str(exc.detail))
        else:
            message = str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content=ResponseModel(code=exc.status_code, message=message, data=None).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        detail_parts = []
        for err in errors:
            loc = " -> ".join(str(part) for part in err.get("loc", []))
            msg = err.get("msg", "")
            detail_parts.append(f"{loc}: {msg}" if loc else msg)
        detail = "; ".join(detail_parts)
        return JSONResponse(
            status_code=422,
            content=ResponseModel(code=422, message=detail, data=None).model_dump(),
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        # ValueError 可能是内部实现细节，不暴露给客户端
        logger.warning("ValueError: %s, path=%s", str(exc), request.url.path)
        return JSONResponse(
            status_code=400,
            content=ResponseModel(code=400, message="请求参数错误", data=None).model_dump(),
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled exception: %s, path: %s", str(exc), request.url.path, exc_info=True)
        return JSONResponse(
            status_code=500,
            content=ResponseModel(code=500, message="服务器内部错误", data=None).model_dump(),
        )
