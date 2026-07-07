"""JMESPath 响应转换器 — 将 API 原始 JSON 映射为 Agent 视图。"""

from __future__ import annotations

from typing import Any

import jmespath
from jmespath.exceptions import JMESPathError

from framework.commons.logger import get_logger

logger = get_logger("MCP_TRANSFORM")


class TransformError(Exception):
    """响应 DSL 执行失败。"""


class ResponseTransformer:
    """按 JMESPath 表达式裁剪并重命名 API 响应字段。"""

    @staticmethod
    def transform(data: Any, expression: str) -> Any:
        """执行 JMESPath 表达式，返回 Agent 视图。"""
        expr = (expression or "").strip()
        if not expr:
            return data
        try:
            compiled = jmespath.compile(expr)
            result = compiled.search(data)
        except JMESPathError as exc:
            logger.error("JMESPath 解析/执行失败: %s", exc, exc_info=True)
            raise TransformError(f"响应 DSL 无效: {exc}") from exc
        except Exception as exc:
            logger.error("响应转换异常", exc_info=True)
            raise TransformError(f"响应转换失败: {exc}") from exc
        return result
