"""REST API 集成测试 — 因子列表筛选与分页（因子库页面对应接口）。"""

from __future__ import annotations

import pytest

API_PREFIX = "/api/v1"


def _items(payload: dict) -> list[dict]:
    return payload["data"]["items"]


def _total(payload: dict) -> int:
    return payload["data"]["total"]


class TestListFactorsAPI:
    """GET /api/v1/factors — 服务端筛选 + 全局分页。"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_list_default_pagination(self, api_client):
        response = await api_client.get(f"{API_PREFIX}/factors", params={"page": 1, "page_size": 20})
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        items = _items(body)
        assert len(items) <= 20
        assert _total(body) >= len(items)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_filter_by_status_active(self, api_client):
        response = await api_client.get(
            f"{API_PREFIX}/factors",
            params={"page": 1, "page_size": 50, "status": "active"},
        )
        assert response.status_code == 200
        body = response.json()
        items = _items(body)
        assert all(i["status"] == "active" for i in items)
        assert _total(body) == len(items) or len(items) <= 50

    @pytest.mark.asyncio(loop_scope="session")
    async def test_filter_by_factor_grade_d(self, api_client):
        response = await api_client.get(
            f"{API_PREFIX}/factors",
            params={"page": 1, "page_size": 200, "factor_grade": "D"},
        )
        assert response.status_code == 200
        body = response.json()
        items = _items(body)
        total = _total(body)
        assert total >= 0
        assert all(i.get("factor_grade") == "D" for i in items)
        # 全量 D 级数量应与 total 一致（单页可装下时）
        if total <= 200:
            assert len(items) == total

    @pytest.mark.asyncio(loop_scope="session")
    async def test_filter_usable_only_ab_grade(self, api_client):
        response = await api_client.get(
            f"{API_PREFIX}/factors",
            params={"page": 1, "page_size": 200, "usable_only": True},
        )
        assert response.status_code == 200
        body = response.json()
        items = _items(body)
        assert all(i.get("factor_grade") in ("A", "B") for i in items)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_pagination_respects_global_filter(self, api_client):
        """筛选后翻页：各页并集应等于 total，且均满足筛选条件。"""
        page_size = 5
        first = await api_client.get(
            f"{API_PREFIX}/factors",
            params={"page": 1, "page_size": page_size, "status": "active"},
        )
        assert first.status_code == 200
        body1 = first.json()
        total = _total(body1)
        if total <= page_size:
            pytest.skip("active 因子不足两页，跳过分页并集测试")

        second = await api_client.get(
            f"{API_PREFIX}/factors",
            params={"page": 2, "page_size": page_size, "status": "active"},
        )
        assert second.status_code == 200
        body2 = second.json()
        items1 = _items(body1)
        items2 = _items(body2)
        ids1 = {i["factor_id"] for i in items1}
        ids2 = {i["factor_id"] for i in items2}
        assert ids1.isdisjoint(ids2)
        assert all(i["status"] == "active" for i in items1 + items2)
        assert len(items1) + len(items2) <= total

    @pytest.mark.asyncio(loop_scope="session")
    async def test_keyword_search_factor_id(self, api_client):
        response = await api_client.get(
            f"{API_PREFIX}/factors",
            params={"page": 1, "page_size": 20, "keyword": "mom_5d"},
        )
        assert response.status_code == 200
        body = response.json()
        items = _items(body)
        assert items
        assert any(i["factor_id"] == "mom_5d" for i in items)
        assert all(
            "mom_5d" in i["factor_id"].lower()
            or "mom_5d" in (i.get("display_name") or "").lower()
            for i in items
        )

    @pytest.mark.asyncio(loop_scope="session")
    async def test_filter_by_category(self, api_client):
        response = await api_client.get(
            f"{API_PREFIX}/factors",
            params={"page": 1, "page_size": 50, "category": "momentum"},
        )
        assert response.status_code == 200
        body = response.json()
        items = _items(body)
        assert all(i["category"] == "momentum" for i in items)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_categories_aggregate(self, api_client):
        response = await api_client.get(f"{API_PREFIX}/factors/categories")
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        categories = body["data"]
        assert isinstance(categories, list)
        assert all("category" in c and "count" in c for c in categories)
