"""数据中心 API 路由。"""

from fastapi import APIRouter, Query

from xqtrader.domain.data.services.data_service import DataService

router = APIRouter(prefix="/data", tags=["数据中心"])

_service = DataService()


@router.get("/summary", summary="数据概览摘要")
async def get_data_summary() -> dict:
    """返回管线数、标的数、记录数、存储占用等摘要信息。"""
    return await _service.get_summary()


@router.get("/watermarks", summary="水位概览")
async def get_watermarks() -> dict:
    """按管线聚合水位统计，包含覆盖率、滞后天数等。"""
    return await _service.get_watermarks()


@router.get("/tables", summary="数据表统计")
async def get_stock_tables() -> list:
    """查询数据库所有用户表的大小、行数等统计信息。"""
    return await _service.get_tables()


@router.get("/overview", summary="综合概览")
async def get_data_overview() -> dict:
    """一次返回摘要 + 水位 + 表统计。"""
    return await _service.get_overview()


@router.get("/tasks", summary="采集任务列表")
async def get_collect_tasks() -> list:
    """返回所有采集任务的详细信息，包含状态、调度、参数等。"""
    return await _service.get_tasks()


@router.post("/tasks/{task_id}/trigger", summary="触发采集任务")
async def trigger_collect_task(task_id: str, params: dict | None = None) -> dict:
    """手动触发指定采集任务，可附带运行参数。"""
    return await _service.trigger_task(task_id, params)


@router.get("/tasks/{task_id}/logs", summary="任务执行日志")
async def get_task_logs(
    task_id: str,
    level: str | None = Query(default=None, description="日志级别过滤"),
    limit: int = Query(default=50, ge=1, le=200, description="每页数量"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
) -> dict:
    """查询指定任务的执行日志。"""
    return await _service.get_task_logs(task_id, level=level, limit=limit, offset=offset)


@router.get("/nodes", summary="工作节点列表")
async def get_nodes() -> list:
    """查询 Celery Worker 节点信息。"""
    return await _service.get_nodes()
