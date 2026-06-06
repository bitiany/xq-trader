"""工作流执行记录管理器。

封装 WorkflowRun 模型的 CRUD 操作，提供简洁的状态管理接口。
API 层通过此管理器与数据库交互，无需直接操作 ORM。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from framework.commons.logger import get_logger
from framework.workflow.models import WorkflowRun

logger = get_logger(__name__)


class WorkflowRunManager:
    """工作流执行记录管理器。

    封装所有 WorkflowRun 的 CRUD 操作，面向对象设计，
    API 层通过此管理器与数据库交互。
    """

    @staticmethod
    def _generate_run_id() -> str:
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        short = uuid.uuid4().hex[:8]
        return f"run_{ts}_{short}"

    async def create(
        self,
        flow_id: str,
        thread_id: str,
        inputs: dict[str, Any],
        workspace_id: str = "",
        total_steps: int = 0,
    ) -> WorkflowRun:
        """创建工作流执行记录。"""
        run_id = self._generate_run_id()
        run = await WorkflowRun.create(
            run_id=run_id,
            flow_id=flow_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            status="running",
            inputs=json.dumps(inputs, ensure_ascii=False),
            total_steps=total_steps,
        )
        logger.info(f"WorkflowRun created | run_id: {run_id} | flow_id: {flow_id}")
        return run

    async def get(self, run_id: str) -> WorkflowRun | None:
        """按 run_id 查询执行记录。"""
        return await WorkflowRun.get_one_or_none(run_id=run_id)

    async def update_status(
        self,
        run_id: str,
        status: str,
        *,
        current_node_id: str = "",
        current_node_title: str = "",
        outputs: dict[str, Any] | None = None,
        interrupt_data: dict[str, Any] | None = None,
        error: str = "",
        elapsed_time: float = 0.0,
    ) -> WorkflowRun | None:
        """更新执行记录状态。"""
        run = await self.get(run_id)
        if run is None:
            logger.warning(f"WorkflowRun not found | run_id: {run_id}")
            return None

        update_data: dict[str, Any] = {"status": status}

        if current_node_id:
            update_data["current_node_id"] = current_node_id
        if current_node_title:
            update_data["current_node_title"] = current_node_title
        if outputs is not None:
            update_data["outputs"] = json.dumps(outputs, ensure_ascii=False)
        if interrupt_data is not None:
            update_data["interrupt_data"] = json.dumps(interrupt_data, ensure_ascii=False)
        if error:
            update_data["error"] = error
        if elapsed_time > 0:
            update_data["elapsed_time"] = elapsed_time

        if status in ("succeeded", "failed", "stopped"):
            update_data["finished_at"] = datetime.now()

        await run.update(update_data)
        logger.info(
            f"WorkflowRun updated | run_id: {run_id} | status: {status}"
            + (f" | node: {current_node_id}" if current_node_id else "")
        )
        return run

    async def get_thread_id(self, run_id: str) -> str | None:
        """通过 run_id 获取内部 thread_id。"""
        run = await self.get(run_id)
        if run is None:
            return None
        return run.thread_id

    async def get_flow_id(self, run_id: str) -> str | None:
        """通过 run_id 获取 flow_id。"""
        run = await self.get(run_id)
        if run is None:
            return None
        return run.flow_id

    def to_dict(self, run: WorkflowRun) -> dict[str, Any]:
        """将 WorkflowRun 实例转换为 API 响应字典。"""
        result: dict[str, Any] = {
            "run_id": run.run_id,
            "flow_id": run.flow_id,
            "workspace_id": run.workspace_id,
            "status": run.status,
            "current_node_id": run.current_node_id,
            "current_node_title": run.current_node_title,
            "total_steps": run.total_steps,
            "elapsed_time": run.elapsed_time,
            "created_at": str(run.created_at) if run.created_at else None,
            "finished_at": str(run.finished_at) if run.finished_at else None,
        }

        try:
            result["inputs"] = json.loads(run.inputs) if run.inputs else {}
        except (json.JSONDecodeError, TypeError):
            result["inputs"] = {}

        try:
            result["outputs"] = json.loads(run.outputs) if run.outputs else {}
        except (json.JSONDecodeError, TypeError):
            result["outputs"] = {}

        try:
            result["interrupt"] = (
                json.loads(run.interrupt_data)
                if run.interrupt_data and run.interrupt_data != "{}"
                else None
            )
        except (json.JSONDecodeError, TypeError):
            result["interrupt"] = None

        if run.error:
            result["error"] = run.error

        return result


# 全局单例
run_manager = WorkflowRunManager()
