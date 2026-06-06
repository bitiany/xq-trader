"""工作流 API 全场景集成测试。

覆盖场景：
  1. 串行工作流 — 正常执行完成
  2. 并行工作流 — fan-out/fan-in 并行执行
  3. 人工确认 — 中断 + 恢复
  4. 分支路由 — Switch 节点 + 人工确认 + approve/reject 分支
  5. 异常处理 — 工具节点抛出异常
  6. 停止工作流
  7. 错误场景 — 404/400

每个场景都验证：
  - API 响应正确
  - 数据库 t_workflow_run 记录正确
  - checkpoint 数据已写入
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx
import pytest
import pytest_asyncio

SRC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


def _unwrap(resp: httpx.Response) -> Any:
    data = resp.json()
    if isinstance(data, dict) and "code" in data and "data" in data:
        return data["data"]
    return data


# ==================== 数据库验证辅助 ====================

async def _db_query(sql: str) -> list[dict[str, Any]]:
    """通过 ORM 直接查询数据库。"""
    from framework.dal.enginee import engines_manager
    engine = engines_manager.get_engine("default")
    from sqlalchemy import text
    async with engine.connect() as conn:
        result = await conn.execute(text(sql))
        rows = result.mappings().all()
        return [dict(row) for row in rows]


async def _verify_run_in_db(run_id: str, expected: dict[str, Any]) -> None:
    """验证 t_workflow_run 中的记录。"""
    rows = await _db_query(
        f"SELECT run_id, flow_id, status, current_node_id, thread_id, "
        f"inputs, outputs, interrupt_data, error, total_steps "
        f"FROM public.t_workflow_run WHERE run_id = '{run_id}'"
    )
    assert len(rows) == 1, f"Expected 1 row for run_id={run_id}, got {len(rows)}"
    row = rows[0]

    for key, expected_val in expected.items():
        actual_val = row.get(key)
        if key in ("inputs", "outputs", "interrupt_data"):
            actual_val = json.loads(actual_val) if actual_val else {}
        assert actual_val == expected_val, (
            f"DB verify failed for {key}: expected={expected_val}, actual={actual_val}"
        )


async def _verify_checkpoints_exist(thread_id: str) -> int:
    """验证 checkpoint 数据已写入，返回 checkpoint 数量。"""
    rows = await _db_query(
        f"SELECT COUNT(*) as cnt FROM public.checkpoints "
        f"WHERE thread_id = '{thread_id}'"
    )
    return rows[0]["cnt"]


# ==================== Fixture ====================

@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def workflow_client():
    from xqtrader.main import create_app
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


# ==================== 1. 串行工作流 ====================

class TestSerialWorkflow:
    """串行工作流：start -> tool_a -> tool_b -> end"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_serial_succeeded(self, workflow_client: httpx.AsyncClient):
        resp = await workflow_client.post(
            "/api/v1/workflow/run",
            json={"flow_id": "test_api_serial", "inputs": {"input_value": "serial_test"}},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "succeeded"
        assert data["flow_id"] == "test_api_serial"
        assert data["run_id"].startswith("run_")
        assert data["outputs"]["tool_a"] == "serial_test"
        assert data["outputs"]["tool_b"] == "serial_test"

        # 数据库验证
        await _verify_run_in_db(data["run_id"], {
            "run_id": data["run_id"],
            "flow_id": "test_api_serial",
            "status": "succeeded",
        })

        # checkpoint 验证
        thread_id = (await _db_query(
            f"SELECT thread_id FROM public.t_workflow_run WHERE run_id = '{data['run_id']}'"
        ))[0]["thread_id"]
        cp_count = await _verify_checkpoints_exist(thread_id)
        assert cp_count > 0, "Expected checkpoints to be persisted"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_serial_get_status(self, workflow_client: httpx.AsyncClient):
        run_resp = await workflow_client.post(
            "/api/v1/workflow/run",
            json={"flow_id": "test_api_serial", "inputs": {"input_value": "status_check"}},
        )
        run_data = _unwrap(run_resp)
        run_id = run_data["run_id"]

        status_resp = await workflow_client.get(f"/api/v1/workflow/run/{run_id}")
        assert status_resp.status_code == 200
        status_data = _unwrap(status_resp)
        assert status_data["status"] == "succeeded"
        assert status_data["run_id"] == run_id


# ==================== 2. 并行工作流 ====================

class TestParallelWorkflow:
    """并行工作流：start -> [tool_a, tool_b, tool_c] -> merge -> end"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_parallel_succeeded(self, workflow_client: httpx.AsyncClient):
        resp = await workflow_client.post(
            "/api/v1/workflow/run",
            json={"flow_id": "test_parallel", "inputs": {"input_value": "par_test"}},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "succeeded"
        assert data["flow_id"] == "test_parallel"

        # 并行分支结果
        outputs = data["outputs"]
        assert outputs.get("tool_a") == "branch_A_par_test"
        assert outputs.get("tool_b") == "branch_B_par_test"
        assert outputs.get("tool_c") == "branch_C_par_test"

        # 数据库验证
        await _verify_run_in_db(data["run_id"], {
            "run_id": data["run_id"],
            "flow_id": "test_parallel",
            "status": "succeeded",
        })

        # checkpoint 验证
        thread_id = (await _db_query(
            f"SELECT thread_id FROM public.t_workflow_run WHERE run_id = '{data['run_id']}'"
        ))[0]["thread_id"]
        cp_count = await _verify_checkpoints_exist(thread_id)
        assert cp_count > 0, "Expected checkpoints for parallel workflow"


# ==================== 3. 人工确认 ====================

class TestHumanInputWorkflow:
    """人工确认：start -> tool_a -> review -> end"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_hitl_interrupt_and_resume(self, workflow_client: httpx.AsyncClient):
        # 启动 → 中断
        run_resp = await workflow_client.post(
            "/api/v1/workflow/run",
            json={"flow_id": "test_api_hitl", "inputs": {"input_value": "hitl_test"}},
        )
        assert run_resp.status_code == 200
        run_data = _unwrap(run_resp)
        assert run_data["status"] == "paused"
        assert run_data["current_node_id"] == "review"
        assert "thread_id" not in run_data  # 不暴露内部字段

        interrupt = run_data.get("interrupt")
        assert interrupt is not None
        assert interrupt["node_id"] == "review"
        assert interrupt["node_type"] == "human_input"

        run_id = run_data["run_id"]

        # 数据库验证：paused 状态
        await _verify_run_in_db(run_id, {
            "run_id": run_id,
            "flow_id": "test_api_hitl",
            "status": "paused",
            "current_node_id": "review",
        })

        # 查询状态
        status_resp = await workflow_client.get(f"/api/v1/workflow/run/{run_id}")
        assert status_resp.status_code == 200
        status_data = _unwrap(status_resp)
        assert status_data["status"] == "paused"

        # 恢复
        resume_resp = await workflow_client.post(
            f"/api/v1/workflow/run/{run_id}/resume",
            json={"resume_value": {"action": "approve", "form_data": {"confirmed": "yes"}}},
        )
        assert resume_resp.status_code == 200
        resume_data = _unwrap(resume_resp)
        assert resume_data["status"] == "succeeded"

        # 数据库验证：succeeded 状态
        await _verify_run_in_db(run_id, {
            "run_id": run_id,
            "flow_id": "test_api_hitl",
            "status": "succeeded",
        })


# ==================== 4. 分支路由 ====================

class TestSwitchWorkflow:
    """分支路由：start -> tool_a -> review -> switch -> (approve_path/reject_path) -> end"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_switch_approve(self, workflow_client: httpx.AsyncClient):
        # 启动 → review 中断
        run_resp = await workflow_client.post(
            "/api/v1/workflow/run",
            json={"flow_id": "test_switch", "inputs": {"input_value": "switch_approve"}},
        )
        run_data = _unwrap(run_resp)
        assert run_data["status"] == "paused"
        run_id = run_data["run_id"]

        # 恢复 → approve 分支
        resume_resp = await workflow_client.post(
            f"/api/v1/workflow/run/{run_id}/resume",
            json={"resume_value": {"action": "approve", "form_data": {"comment": "ok"}}},
        )
        assert resume_resp.status_code == 200
        resume_data = _unwrap(resume_resp)
        assert resume_data["status"] == "succeeded"

        outputs = resume_data["outputs"]
        assert outputs.get("approve_path") == "APPROVED_switch_approve"

        # 数据库验证
        await _verify_run_in_db(run_id, {
            "run_id": run_id,
            "flow_id": "test_switch",
            "status": "succeeded",
        })

    @pytest.mark.asyncio(loop_scope="session")
    async def test_switch_reject(self, workflow_client: httpx.AsyncClient):
        # 启动 → review 中断
        run_resp = await workflow_client.post(
            "/api/v1/workflow/run",
            json={"flow_id": "test_switch", "inputs": {"input_value": "switch_reject"}},
        )
        run_data = _unwrap(run_resp)
        run_id = run_data["run_id"]

        # 恢复 → reject 分支
        resume_resp = await workflow_client.post(
            f"/api/v1/workflow/run/{run_id}/resume",
            json={"resume_value": {"action": "reject", "form_data": {"comment": "bad"}}},
        )
        assert resume_resp.status_code == 200
        resume_data = _unwrap(resume_resp)
        assert resume_data["status"] == "succeeded"

        outputs = resume_data["outputs"]
        assert outputs.get("reject_path") == "REJECTED_switch_reject"

        # 数据库验证
        await _verify_run_in_db(run_id, {
            "run_id": run_id,
            "flow_id": "test_switch",
            "status": "succeeded",
        })


# ==================== 5. 异常处理 ====================

class TestErrorWorkflow:
    """异常工作流：start -> tool_a -> fail_node -> end"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_error_workflow(self, workflow_client: httpx.AsyncClient):
        resp = await workflow_client.post(
            "/api/v1/workflow/run",
            json={"flow_id": "test_error", "inputs": {"input_value": "error_test"}},
        )
        assert resp.status_code == 500

        # 数据库验证：failed 状态
        rows = await _db_query(
            "SELECT run_id, flow_id, status, error FROM public.t_workflow_run "
            "WHERE flow_id = 'test_error' ORDER BY created_at DESC LIMIT 1"
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["status"] == "failed"
        assert "deliberate_error_error_test" in row["error"]

        # 验证 run_id 格式
        assert row["run_id"].startswith("run_")


# ==================== 6. 停止工作流 ====================

class TestStopWorkflow:
    """停止工作流"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_stop_paused_workflow(self, workflow_client: httpx.AsyncClient):
        # 启动 → 中断
        run_resp = await workflow_client.post(
            "/api/v1/workflow/run",
            json={"flow_id": "test_api_hitl", "inputs": {"input_value": "stop_test"}},
        )
        run_data = _unwrap(run_resp)
        assert run_data["status"] == "paused"
        run_id = run_data["run_id"]

        # 停止
        stop_resp = await workflow_client.post(f"/api/v1/workflow/run/{run_id}/stop")
        assert stop_resp.status_code == 200
        stop_data = _unwrap(stop_resp)
        assert stop_data["status"] == "stopped"

        # 数据库验证
        await _verify_run_in_db(run_id, {
            "run_id": run_id,
            "flow_id": "test_api_hitl",
            "status": "stopped",
        })

    @pytest.mark.asyncio(loop_scope="session")
    async def test_stop_succeeded_workflow_fails(self, workflow_client: httpx.AsyncClient):
        run_resp = await workflow_client.post(
            "/api/v1/workflow/run",
            json={"flow_id": "test_api_serial", "inputs": {"input_value": "completed"}},
        )
        run_data = _unwrap(run_resp)
        run_id = run_data["run_id"]

        stop_resp = await workflow_client.post(f"/api/v1/workflow/run/{run_id}/stop")
        assert stop_resp.status_code == 400


# ==================== 7. 错误场景 ====================

class TestErrorScenarios:
    """404/400 错误场景"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_nonexistent_run(self, workflow_client: httpx.AsyncClient):
        resp = await workflow_client.get("/api/v1/workflow/run/nonexistent_id")
        assert resp.status_code == 404

    @pytest.mark.asyncio(loop_scope="session")
    async def test_resume_nonexistent_run(self, workflow_client: httpx.AsyncClient):
        resp = await workflow_client.post(
            "/api/v1/workflow/run/nonexistent_id/resume",
            json={"resume_value": {"action": "approve"}},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio(loop_scope="session")
    async def test_resume_succeeded_workflow(self, workflow_client: httpx.AsyncClient):
        run_resp = await workflow_client.post(
            "/api/v1/workflow/run",
            json={"flow_id": "test_api_serial", "inputs": {"input_value": "done"}},
        )
        run_data = _unwrap(run_resp)
        run_id = run_data["run_id"]

        resume_resp = await workflow_client.post(
            f"/api/v1/workflow/run/{run_id}/resume",
            json={"resume_value": {"action": "approve"}},
        )
        assert resume_resp.status_code == 400

    @pytest.mark.asyncio(loop_scope="session")
    async def test_run_nonexistent_flow(self, workflow_client: httpx.AsyncClient):
        resp = await workflow_client.post(
            "/api/v1/workflow/run",
            json={"flow_id": "nonexistent_flow", "inputs": {}},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio(loop_scope="session")
    async def test_stop_nonexistent_run(self, workflow_client: httpx.AsyncClient):
        resp = await workflow_client.post("/api/v1/workflow/run/nonexistent_id/stop")
        assert resp.status_code == 404


# ==================== 8. 列表接口 ====================

class TestWorkflowList:
    """GET /workflow/list"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_list_workflows(self, workflow_client: httpx.AsyncClient):
        resp = await workflow_client.get("/api/v1/workflow/list")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert isinstance(data, list)
        flow_ids = [f["flow_id"] for f in data]
        assert "test_api_serial" in flow_ids
        assert "test_parallel" in flow_ids
        assert "test_switch" in flow_ids
        assert "test_error" in flow_ids
