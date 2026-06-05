"""Framework 单元测试 — 数据库 ORM 查询验证。"""

import pytest
from xqtrader.domain.security.models import Security  # noqa: I001


@pytest.mark.asyncio(loop_scope="session")
async def test_security_filter(app_with_datasource):
    items = await Security.filter(industry="银行", limit=10)
    assert len(items) > 0
    assert all(item.industry == "银行" for item in items)

    total = await Security.count(industry="银行")
    assert total > 0

    page_items = await Security.filter(skip=0, limit=1)
    assert len(page_items) == 1
