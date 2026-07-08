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
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from framework.commons.logger import get_logger
from framework.config.settings import settings
from framework.workflow import FlowEngine
from framework.workflow.run_manager import run_manager
from xqtrader.domain.workflow.dispatch import (
    WorkflowExecutionError,
    WorkflowNotFoundError,
    _run_engine,
    execute_workflow,
    load_flow_config,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/workflow", tags=["workflow"])


class WorkflowRunRequest(BaseModel):
    """启动工作流请求 — 业务侧只需提供 flow_id 和输入参数。"""
    flow_id: str = Field(description="工作流ID")
    workspace_id: str = Field(default="", description="工作空间ID")
    inputs: dict[str, Any] = Field(default_factory=dict, description="工作流输入参数")


class WorkflowResumeRequest(BaseModel):
    """恢复工作流请求 — 业务侧只需提供 resume_value。"""
    resume_value: Any = Field(description="恢复值（用户提交的表单数据 + 动作）")


@router.post("/run")
async def workflow_run(request: WorkflowRunRequest) -> dict:
    """启动工作流执行。"""
    try:
        return await execute_workflow(
            flow_id=request.flow_id,
            inputs=request.inputs,
            workspace_id=request.workspace_id,
        )
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkflowExecutionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/run/{run_id}")
async def workflow_get_run(run_id: str) -> dict:
    """查询工作流执行状态。"""
    run = await run_manager.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"执行记录 '{run_id}' 不存在")
    return run_manager.to_dict(run)


@router.post("/run/{run_id}/resume")
async def workflow_resume(run_id: str, request: WorkflowResumeRequest) -> dict:
    """恢复中断的工作流。"""
    run = await run_manager.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"执行记录 '{run_id}' 不存在")

    if run.status != "paused":
        raise HTTPException(
            status_code=400,
            detail=f"工作流当前状态为 '{run.status}'，无法恢复（仅 paused 状态可恢复）",
        )

    thread_id = run.thread_id
    flow_id = run.flow_id

    config = load_flow_config(flow_id)
    engine = FlowEngine(config)

    start_time = time.time()
    logger.info(
        "workflow_resume | run_id: %s | flow_id: %s | thread_id: %s",
        run_id,
        flow_id,
        thread_id,
    )

    await run_manager.update_status(run_id, "running")

    try:
        return await _run_engine(
            run_id,
            engine,
            start_time,
            resume_value=request.resume_value,
            config={"thread_id": thread_id, "execute_id": run_id},
        )
    except WorkflowExecutionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/run/{run_id}/stop")
async def workflow_stop(run_id: str) -> dict:
    """停止工作流执行。"""
    run = await run_manager.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"执行记录 '{run_id}' 不存在")

    if run.status not in ("running", "paused"):
        raise HTTPException(
            status_code=400,
            detail=f"工作流当前状态为 '{run.status}'，无法停止",
        )

    await run_manager.update_status(run_id, "stopped")
    run_record = await run_manager.get(run_id)
    return run_manager.to_dict(run_record)  # type: ignore[arg-type]


@router.get("/list")
async def workflow_list() -> list[dict]:
    """列出可用工作流。"""
    flow_dir = os.path.join(settings.APP.ROOT_DIR, "flow")
    flows: list[dict] = []
    if os.path.isdir(flow_dir):
        for fname in os.listdir(flow_dir):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(flow_dir, fname), encoding="utf-8") as handle:
                        cfg = json.load(handle)
                    flows.append({
                        "flow_id": cfg.get("id", fname.replace(".json", "")),
                        "name": cfg.get("id", fname.replace(".json", "")),
                        "description": cfg.get("description", ""),
                    })
                except Exception as exc:
                    logger.error("Failed to load flow config '%s': %s", fname, exc, exc_info=True)
    return flows
