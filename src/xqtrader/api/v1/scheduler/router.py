"""调度管理 API — 任务查询、手动触发、编排管理。"""

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from framework.commons.exceptions import NotFoundException
from framework.commons.pagination import build_paginated_response, paginate
from worker.models import PipelineDef, TaskDef, TaskExec

router = APIRouter(prefix="/scheduler", tags=["调度管理"])


@router.get("/tasks", summary="查询任务定义列表")
async def list_task_defs(
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
) -> dict:
    skip, limit = paginate(page, page_size)
    items = await TaskDef.filter(skip=skip, limit=limit)
    total = await TaskDef.count()
    return build_paginated_response(
        [item.to_dict() for item in items], total, page, page_size
    )


@router.get("/tasks/{task_name}", summary="查询任务详情")
async def get_task_def(task_name: str) -> dict:
    task = await TaskDef.get_one_or_none(name=task_name)
    if task is None:
        raise NotFoundException(message=f"任务 {task_name} 不存在")
    return task.to_dict()


class TriggerTaskRequest(BaseModel):
    """手动触发任务请求体。"""

    kwargs: dict[str, Any] | None = None


@router.post("/tasks/{task_name}/trigger", summary="手动触发任务")
async def trigger_task(task_name: str, body: TriggerTaskRequest | None = None) -> dict:
    task_def = await TaskDef.get_one_or_none(name=task_name)
    if task_def is None:
        raise NotFoundException(message=f"任务 {task_name} 不存在")
    from worker.celery_app import celery_app

    task_kwargs = body.kwargs if body and body.kwargs else {}
    result = celery_app.send_task(task_name, kwargs=task_kwargs)
    return {"task_id": result.id, "task_name": task_name, "status": "PENDING"}


@router.get("/tasks/{task_name}/executions", summary="查询任务执行历史")
async def list_task_executions(
    task_name: str,
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
) -> dict:
    skip, limit = paginate(page, page_size)
    items = await TaskExec.filter(task_name=task_name, skip=skip, limit=limit)
    total = await TaskExec.count(task_name=task_name)
    return build_paginated_response(
        [item.to_dict() for item in items], total, page, page_size
    )


@router.get("/pipelines", summary="查询编排列表")
async def list_pipelines(
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
) -> dict:
    skip, limit = paginate(page, page_size)
    items = await PipelineDef.filter(skip=skip, limit=limit)
    total = await PipelineDef.count()
    return build_paginated_response(
        [item.to_dict() for item in items], total, page, page_size
    )


@router.get("/pipelines/{pipeline_name}", summary="查询编排详情")
async def get_pipeline(pipeline_name: str) -> dict:
    pipeline = await PipelineDef.get_one_or_none(name=pipeline_name)
    if pipeline is None:
        raise NotFoundException(message=f"编排 {pipeline_name} 不存在")
    return pipeline.to_dict()


@router.post("/pipelines/{pipeline_name}/trigger", summary="手动触发编排")
async def trigger_pipeline(pipeline_name: str) -> dict:
    pipeline = await PipelineDef.get_one_or_none(name=pipeline_name)
    if pipeline is None:
        raise NotFoundException(message=f"编排 {pipeline_name} 不存在")
    from worker.celery_app import celery_app

    result = celery_app.send_task(
        "worker.orchestration.trigger_pipeline",
        kwargs={"pipeline_name": pipeline_name},
    )
    return {"task_id": result.id, "pipeline_name": pipeline_name, "status": "PENDING"}


@router.get("/pipelines/{pipeline_name}/executions", summary="查询编排执行历史")
async def list_pipeline_executions(
    pipeline_name: str,
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
) -> dict:
    skip, limit = paginate(page, page_size)
    items = await TaskExec.filter(task_name=pipeline_name, task_type="pipeline", skip=skip, limit=limit)
    total = await TaskExec.count(task_name=pipeline_name, task_type="pipeline")
    return build_paginated_response(
        [item.to_dict() for item in items], total, page, page_size
    )


@router.get("/pipelines/{pipeline_name}/executions/{exec_id}/children", summary="查询编排子任务列表")
async def list_pipeline_children(
    pipeline_name: str,
    exec_id: str,
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
) -> dict:
    parent = await TaskExec.get_one_or_none(id=exec_id)
    if parent is None or parent.task_type != "pipeline":
        raise NotFoundException(message=f"编排执行记录 {exec_id} 不存在")
    skip, limit = paginate(page, page_size)
    items = await TaskExec.filter(parent_id=exec_id, skip=skip, limit=limit)
    total = await TaskExec.count(parent_id=exec_id)
    return build_paginated_response(
        [item.to_dict() for item in items], total, page, page_size
    )


@router.post("/pipelines/{pipeline_name}/executions/{exec_id}/retry", summary="重试失败的编排")
async def retry_pipeline_exec(pipeline_name: str, exec_id: str) -> dict:
    parent = await TaskExec.get_one_or_none(id=exec_id)
    if parent is None or parent.task_type != "pipeline":
        raise NotFoundException(message=f"编排执行记录 {exec_id} 不存在")
    if parent.status not in ("FAILURE", "FAILED"):
        raise NotFoundException(message=f"编排执行记录 {exec_id} 状态为 {parent.status}，仅失败记录可重试")

    from worker.celery_app import celery_app

    result = celery_app.send_task(
        "worker.orchestration.recover_pipeline",
        kwargs={"orchestration_id": exec_id},
    )
    return {"task_id": result.id, "pipeline_name": pipeline_name, "orchestration_id": exec_id, "status": "RECOVERING"}
