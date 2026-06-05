"""日志配置与工具。"""

import logging
import sys
from typing import Any

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_root_configured: bool = False


def setup_logging(level: int = logging.INFO) -> None:
    """初始化根日志配置，全局只执行一次。"""
    global _root_configured
    if _root_configured:
        return
    _root_configured = True

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)

    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True


def get_logger(name: str) -> logging.Logger:
    """获取命名日志器。首次调用时自动初始化根配置。"""
    if not _root_configured:
        setup_logging()
    return logging.getLogger(name)


class RequestContextLogger:
    """带请求上下文的日志适配器，自动附加 request_id。"""

    def __init__(self, logger: logging.Logger, request_id: str = "") -> None:
        self._logger = logger
        self._request_id = request_id

    def _prefix(self) -> str:
        return f"[{self._request_id}] " if self._request_id else ""

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.info(self._prefix() + msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.warning(self._prefix() + msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.error(self._prefix() + msg, *args, **kwargs)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.debug(self._prefix() + msg, *args, **kwargs)
