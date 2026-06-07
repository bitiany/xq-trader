"""分页工具函数 — 统一分页计算和响应构建。"""

from typing import Any


def paginate(page: int, page_size: int) -> tuple[int, int]:
    """计算分页偏移量和限制数。

    Args:
        page: 页码（从 1 开始）
        page_size: 每页数量

    Returns:
        (skip, limit) 元组
    """
    return (page - 1) * page_size, page_size


def build_paginated_response(
    items: list[Any],
    total: int,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """构建统一的分页响应字典。

    Args:
        items: 当前页数据列表
        total: 总记录数
        page: 当前页码
        page_size: 每页数量

    Returns:
        分页响应字典
    """
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
