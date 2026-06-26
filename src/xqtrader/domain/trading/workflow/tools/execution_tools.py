"""预订单执行工作流工具。"""
from __future__ import annotations

from typing import Any, cast

from framework.commons.exceptions import BusinessException, WorkflowConfigError
from framework.dal.transaction.manager import Propagation
from framework.dal.transaction.transactional import transactional
from xqtrader.domain.trading.workflow.execution_service import PreOrderExecutionWorkflowService
from xqtrader.domain.trading.workflow.simulated_matching_service import SimulatedMatchingService

# 模块级共享实例：避免每次工具调用重复创建 service（service 内的 _qmt_trader
# 为类属性缓存，所有实例共享同一 QmtTrader 连接）。
_execution_service = PreOrderExecutionWorkflowService()
# 模拟撮合服务持有 _execution_service 引用（调用其 get_order_for_submit /
# mark_submitted / append_event 公共接口），共享同一 PreOrderExecutionWorkflowService。
_matching_service = SimulatedMatchingService(_execution_service)


def _resolve_operator(input: dict[str, Any]) -> str:
    """从工具输入解析 operator，缺失或为 system 时抛异常。

    与 schemas.validate_operator_not_system 保持一致：禁止 "system" 作为操作人，
    确保审计链路（OrderEvent.operator）记录真实操作人而非系统默认值。
    """
    raw = input.get("operator")
    if not raw or not str(raw).strip():
        raise BusinessException(message="工作流工具缺少 operator 参数，必须传入实际操作人")
    value = str(raw).strip()
    if value.strip().lower() == "system":
        raise BusinessException(message="operator 禁止使用 system，必须填写实际操作人")
    return value


class LoadPreOrderExecutionContextTool:
    async def ainvoke(self, input: dict[str, Any]) -> dict[str, Any]:
        result = await _execution_service.load_execution_context(
            pre_order_id=int(input["pre_order_id"]),
        )
        return cast(dict[str, Any], result)

    def invoke(self, input: dict[str, Any]) -> dict[str, Any]:
        raise WorkflowConfigError("LoadPreOrderExecutionContextTool only supports async execution")


class CreateOrderFromPreOrderTool:
    @transactional(propagation=Propagation.NOT_SUPPORTED)
    async def ainvoke(self, input: dict[str, Any]) -> dict[str, Any]:
        result = await _execution_service.create_order_from_pre_order(
            context=input["context"],
            workflow_run_id=str(input.get("workflow_run_id") or ""),
            operator=_resolve_operator(input),
        )
        return cast(dict[str, Any], result)

    def invoke(self, input: dict[str, Any]) -> dict[str, Any]:
        raise WorkflowConfigError("CreateOrderFromPreOrderTool only supports async execution")


class SubmitSimulatedOrderTool:
    @transactional(propagation=Propagation.NOT_SUPPORTED)
    async def ainvoke(self, input: dict[str, Any]) -> dict[str, Any]:
        result = await _matching_service.submit_simulated_order(
            order_id=int(input["order_id"]),
            operator=_resolve_operator(input),
        )
        return cast(dict[str, Any], result)

    def invoke(self, input: dict[str, Any]) -> dict[str, Any]:
        raise WorkflowConfigError("SubmitSimulatedOrderTool only supports async execution")


class SubmitQmtOrderTool:
    @transactional(propagation=Propagation.NOT_SUPPORTED)
    async def ainvoke(self, input: dict[str, Any]) -> dict[str, Any]:
        result = await _execution_service.submit_qmt_order(
            order_id=int(input["order_id"]),
            operator=_resolve_operator(input),
        )
        return cast(dict[str, Any], result)

    def invoke(self, input: dict[str, Any]) -> dict[str, Any]:
        raise WorkflowConfigError("SubmitQmtOrderTool only supports async execution")
