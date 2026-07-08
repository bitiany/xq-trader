"""工作流执行分发 — API 与 Intent Router 共用。"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from framework.commons.logger import get_logger
from framework.config.settings import settings
from framework.workflow import FlowEngine
from framework.workflow.run_manager import run_manager

logger = get_logger("WORKFLOW_DISPATCH")


class WorkflowNotFoundError(FileNotFoundError):
    """工作流定义不存在。"""


class WorkflowExecutionError(RuntimeError):
    """工作流执行失败。"""


def load_flow_config(flow_id: str) -> dict[str, Any]:
    path = os.path.join(settings.APP.ROOT_DIR, f"flow/{flow_id}.json")
    if not os.path.exists(path):
        raise WorkflowNotFoundError(f"工作流 '{flow_id}' 不存在")
    with open(path, encoding="utf-8") as handle:
        config: dict[str, Any] = json.load(handle)
    return config


def _extract_interrupt_info(result: dict[str, Any]) -> dict[str, Any] | None:
    if "__interrupt__" not in result:
        return None
    interrupts = result["__interrupt__"]
    if not interrupts:
        return None
    first = interrupts[0]
    return first.value if hasattr(first, "value") else first  # type: ignore[no-any-return]


async def _run_engine(
    run_id: str,
    engine: FlowEngine,
    start_time: float,
    **invoke_kwargs: Any,
) -> dict[str, Any]:
    try:
        if "resume_value" in invoke_kwargs:
            result = await engine.aresume(**invoke_kwargs)
        else:
            result = await engine.ainvoke(**invoke_kwargs)
    except Exception as exc:
        elapsed = time.time() - start_time
        await run_manager.update_status(
            run_id,
            "failed",
            error=str(exc),
            elapsed_time=elapsed,
        )
        logger.error("工作流执行失败 | run_id=%s | error=%s", run_id, exc, exc_info=True)
        raise WorkflowExecutionError(str(exc)) from exc

    elapsed = time.time() - start_time
    interrupt_info = _extract_interrupt_info(result)

    if interrupt_info is not None:
        await run_manager.update_status(
            run_id,
            "paused",
            current_node_id=interrupt_info.get("node_id", ""),
            current_node_title=interrupt_info.get("title", ""),
            interrupt_data=interrupt_info,
            elapsed_time=elapsed,
        )
        run_record = await run_manager.get(run_id)
        return run_manager.to_dict(run_record)  # type: ignore[arg-type,return-value]

    outputs = result.get("variables", {})
    await run_manager.update_status(
        run_id,
        "succeeded",
        outputs=outputs,
        elapsed_time=elapsed,
    )
    run_record = await run_manager.get(run_id)
    return run_manager.to_dict(run_record)  # type: ignore[arg-type,return-value]


async def execute_workflow(
    flow_id: str,
    inputs: dict[str, Any],
    workspace_id: str = "",
) -> dict[str, Any]:
    """启动工作流并返回持久化执行记录。"""
    config = load_flow_config(flow_id)
    engine = FlowEngine(config)

    thread_id = str(uuid.uuid4())
    start_time = time.time()

    run = await run_manager.create(
        flow_id=flow_id,
        thread_id=thread_id,
        inputs=inputs,
        workspace_id=workspace_id,
        total_steps=engine.length(),
    )

    logger.info(
        "workflow_run | flow_id=%s | run_id=%s | thread_id=%s",
        flow_id,
        run.run_id,
        thread_id,
    )

    return await _run_engine(
        run.run_id,
        engine,
        start_time,
        inputs=inputs,
        config={"execute_id": run.run_id, "thread_id": thread_id},
    )
