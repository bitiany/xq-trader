"""执行流账户分支路由测试 — 验证 paper→simulated / live→qmt。"""

from __future__ import annotations

import pytest


class TestExecutionSubmitterRouting:
    """submitter 路由由预订单所属实例的账户类型决定，与前端当前选中账户无关。"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_paper_orders_use_sim_broker_id(self, api_client) -> None:
        response = await api_client.get(
            "/api/v1/trading/orders",
            params={"account_id": 1, "page_size": 50},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        orders = body["data"]["items"]
        paper_orders = [item for item in orders if item.get("pre_order_id") == 88]
        if not paper_orders:
            pytest.skip("paper 预订单#88 尚未提交，跳过")
        order = paper_orders[0]
        assert order["broker_order_id"].startswith("SIM-")
        assert order["status"] == "filled"
        assert order["account_id"] == 1

    @pytest.mark.asyncio(loop_scope="session")
    async def test_live_orders_use_qmt_broker_id(self, api_client) -> None:
        response = await api_client.get(
            "/api/v1/trading/orders",
            params={"account_id": 11, "page_size": 50},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        orders = body["data"]["items"]
        qmt_orders = [item for item in orders if item.get("broker_order_id") and not str(item["broker_order_id"]).startswith("SIM-")]
        assert qmt_orders, "live 账户应存在 QMT 订单"
        for order in qmt_orders:
            assert order["account_id"] == 11

    @pytest.mark.asyncio(loop_scope="session")
    async def test_pre_order_list_scoped_by_account_type(self, api_client) -> None:
        """paper 账户预订单列表不应包含 live 实例的预订单。"""
        paper_resp = await api_client.get(
            "/api/v1/trading/pre-orders",
            params={"account_id": 1, "page_size": 100},
        )
        live_resp = await api_client.get(
            "/api/v1/trading/pre-orders",
            params={"account_id": 11, "page_size": 100},
        )
        paper_ids = {item["id"] for item in paper_resp.json()["data"]["items"]}
        live_ids = {item["id"] for item in live_resp.json()["data"]["items"]}
        assert paper_ids.isdisjoint(live_ids)

        paper_instances = {item["instance_id"] for item in paper_resp.json()["data"]["items"]}
        live_instances = {item["instance_id"] for item in live_resp.json()["data"]["items"]}
        assert 2 not in paper_instances, "paper 列表不应出现 live 实例(instance#2)的预订单"
        assert 4 not in live_instances, "live 列表不应出现 paper 实例(instance#4)的预订单"
