"""工作流 API（/api/v1/workflow）。

参照 Dify 工作流 API 设计：
  POST /workflow/run              启动工作流（只需 flow_id + inputs）
  GET  /workflow/run/{run_id}     查询执行状态（内部自动查找 thread_id）
  POST /workflow/run/{run_id}/resume  恢复中断的工作流（只需 run_id + resume_value）
  POST /workflow/run/{run_id}/stop    停止工作流
  GET  /workflow/list             列出可用工作流

设计原则：
  - 业务侧只关心 flow_id 和 run_id，无需了解 thread_id 等内部细节
  - 执行状态由 WorkflowRun 模型持久化，进程重启后仍可查询和恢复
  - 中断信息标准化，前端可统一渲染
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from framework.commons.logger import get_logger
from framework.workflow import FlowEngine
from framework.workflow.run_manager import run_manager

logger = get_logger(__name__)

router = APIRouter(prefix="/workflow", tags=["workflow"])


# ==================== 请求模型 ====================

class WorkflowRunRequest(BaseModel):
    """启动工作流请求 — 业务侧只需提供 flow_id 和输入参数。"""
    flow_id: str = Field(description="工作流ID")
    workspace_id: str = Field(default="", description="工作空间ID")
    inputs: dict[str, Any] = Field(default_factory=dict, description="工作流输入参数")


class WorkflowResumeRequest(BaseModel):
    """恢复工作流请求 — 业务侧只需提供 resume_value。"""
    resume_value: Any = Field(description="恢复值（用户提交的表单数据 + 动作）")


# ==================== 辅助函数 ====================

def _load_flow_config(flow_id: str) -> dict[str, Any]:
    """加载工作流 JSON 配置。"""
    from framework.config.settings import settings

    path = os.path.join(settings.APP.ROOT_DIR, f"flow/{flow_id}.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"工作流 '{flow_id}' 不存在")
    with open(path, encoding="utf-8") as f:
        config: dict[str, Any] = json.load(f)
    return config


def _extract_interrupt_info(result: dict[str, Any]) -> dict[str, Any] | None:
    """从 LangGraph 执行结果中提取中断信息。"""
    if "__interrupt__" not in result:
        return None
    interrupts = result["__interrupt__"]
    if not interrupts:
        return None
    return interrupts[0].value if hasattr(interrupts[0], "value") else interrupts[0]  # type: ignore[no-any-return]


# ==================== API 接口 ====================

@router.post("/run")
async def workflow_run(request: WorkflowRunRequest) -> dict:
    """启动工作流执行。

    参照 Dify: POST /workflows/run
    - 输入: flow_id + inputs
    - 输出: run_id + status + 结果/中断信息
    - thread_id 等内部细节自动管理，不暴露给业务侧
    """
    config = _load_flow_config(request.flow_id)
    engine = FlowEngine(config)

    thread_id = str(uuid.uuid4())
    start_time = time.time()

    # 创建执行记录
    run = await run_manager.create(
        flow_id=request.flow_id,
        thread_id=thread_id,
        inputs=request.inputs,
        workspace_id=request.workspace_id,
        total_steps=engine.length(),
    )

    logger.info(
        f"workflow_run | flow_id: {request.flow_id} | "
        f"run_id: {run.run_id} | thread_id: {thread_id}"
    )

    try:
        result = await engine.ainvoke(
            inputs=request.inputs,
            config={"execute_id": run.run_id, "thread_id": thread_id},
        )
    except Exception as e:
        elapsed = time.time() - start_time
        await run_manager.update_status(
            run.run_id, "failed", error=str(e), elapsed_time=elapsed
        )
        logger.error(f"workflow_run failed | run_id: {run.run_id} | error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"工作流执行失败: {e}")

    elapsed = time.time() - start_time
    interrupt_info = _extract_interrupt_info(result)

    if interrupt_info is not None:
        # 工作流被中断（HumanInput 节点）
        await run_manager.update_status(
            run.run_id,
            "paused",
            current_node_id=interrupt_info.get("node_id", ""),
            current_node_title=interrupt_info.get("title", ""),
            interrupt_data=interrupt_info,
            elapsed_time=elapsed,
        )
        run_record = await run_manager.get(run.run_id)
        return run_manager.to_dict(run_record)  # type: ignore[arg-type]

    # 工作流正常完成
    outputs = result.get("variables", {})
    await run_manager.update_status(
        run.run_id,
        "succeeded",
        outputs=outputs,
        elapsed_time=elapsed,
    )
    run_record = await run_manager.get(run.run_id)
    return run_manager.to_dict(run_record)  # type: ignore[arg-type]


@router.get("/run/{run_id}")
async def workflow_get_run(run_id: str) -> dict:
    """查询工作流执行状态。

    参照 Dify: GET /workflows/run/{workflow_run_id}
    - 输入: run_id
    - 输出: 完整执行状态（含 inputs/outputs/interrupt/error）
    - 内部自动查找 thread_id，业务侧无需关心
    """
    run = await run_manager.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"执行记录 '{run_id}' 不存在")
    return run_manager.to_dict(run)


@router.post("/run/{run_id}/resume")
async def workflow_resume(run_id: str, request: WorkflowResumeRequest) -> dict:
    """恢复中断的工作流。

    参照 Dify: POST /api/form/human_input/{form_token}
    - 输入: run_id + resume_value
    - 内部自动查找 thread_id 和 flow_id，重新加载工作流并恢复
    - 业务侧无需关心 thread_id、flow_id 等内部细节
    """
    run = await run_manager.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"执行记录 '{run_id}' 不存在")

    if run.status != "paused":
        raise HTTPException(
            status_code=400,
            detail=f"工作流当前状态为 '{run.status}'，无法恢复（仅 paused 状态可恢复）"
        )

    # 内部自动查找 thread_id 和 flow_id
    thread_id = run.thread_id
    flow_id = run.flow_id

    config = _load_flow_config(flow_id)
    engine = FlowEngine(config)

    start_time = time.time()
    logger.info(
        f"workflow_resume | run_id: {run_id} | "
        f"flow_id: {flow_id} | thread_id: {thread_id}"
    )

    try:
        # 更新状态为 running
        await run_manager.update_status(run_id, "running")

        result = await engine.aresume(
            resume_value=request.resume_value,
            config={"thread_id": thread_id, "execute_id": run_id},
        )
    except Exception as e:
        elapsed = time.time() - start_time
        await run_manager.update_status(
            run_id, "failed", error=str(e), elapsed_time=elapsed
        )
        logger.error(f"workflow_resume failed | run_id: {run_id} | error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"工作流恢复失败: {e}")

    elapsed = time.time() - start_time
    interrupt_info = _extract_interrupt_info(result)

    if interrupt_info is not None:
        # 恢复后再次中断（可能有多个 HumanInput 节点）
        await run_manager.update_status(
            run_id,
            "paused",
            current_node_id=interrupt_info.get("node_id", ""),
            current_node_title=interrupt_info.get("title", ""),
            interrupt_data=interrupt_info,
            elapsed_time=elapsed,
        )
        run_record = await run_manager.get(run_id)
        return run_manager.to_dict(run_record)  # type: ignore[arg-type]

    # 工作流正常完成
    outputs = result.get("variables", {})
    await run_manager.update_status(
        run_id,
        "succeeded",
        outputs=outputs,
        elapsed_time=elapsed,
    )
    run_record = await run_manager.get(run_id)
    return run_manager.to_dict(run_record)  # type: ignore[arg-type]


@router.post("/run/{run_id}/stop")
async def workflow_stop(run_id: str) -> dict:
    """停止工作流执行。"""
    run = await run_manager.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"执行记录 '{run_id}' 不存在")

    if run.status not in ("running", "paused"):
        raise HTTPException(
            status_code=400,
            detail=f"工作流当前状态为 '{run.status}'，无法停止"
        )

    await run_manager.update_status(run_id, "stopped")
    run_record = await run_manager.get(run_id)
    return run_manager.to_dict(run_record)  # type: ignore[arg-type]


@router.get("/list")
async def workflow_list() -> list[dict]:
    """列出可用工作流。"""
    from framework.config.settings import settings
    flow_dir = os.path.join(settings.APP.ROOT_DIR, "flow")
    flows: list[dict] = []
    if os.path.isdir(flow_dir):
        for fname in os.listdir(flow_dir):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(flow_dir, fname), encoding="utf-8") as f:
                        cfg = json.load(f)
                    flows.append({
                        "flow_id": cfg.get("id", fname.replace(".json", "")),
                        "name": cfg.get("id", fname.replace(".json", "")),
                        "description": cfg.get("description", ""),
                    })
                except Exception as e:
                    logger.error(f"Failed to load flow config '{fname}': {e}")
    return flows
