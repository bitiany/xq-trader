"""Worker 插件公共工具函数。"""

from __future__ import annotations

import json
from typing import Any


def parse_list_param(value: Any) -> list[str] | None:
    """解析可能为 JSON 字符串的列表参数。

    支持 None、list、JSON 字符串、逗号分隔字符串。
    """
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
            return [value]
        except (json.JSONDecodeError, TypeError):
            return [v.strip() for v in value.split(",") if v.strip()]
    return None
