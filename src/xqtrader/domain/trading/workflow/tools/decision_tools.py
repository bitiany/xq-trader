"""盘后自选股决策工作流工具。"""
from __future__ import annotations

from typing import Any, cast

from framework.commons.exceptions import WorkflowConfigError
from framework.dal.transaction.manager import Propagation
from framework.dal.transaction.transactional import transactional
from xqtrader.domain.trading.workflow.service import WatchlistDecisionWorkflowService


class LoadTradingContextTool:
    async def ainvoke(self, input: dict[str, Any]) -> dict[str, Any]:
        result = await WatchlistDecisionWorkflowService().load_trading_context(
            instance_id=int(input["instance_id"]),
            signal_date=input["signal_date"],
            execution_date=input.get("execution_date") or None,
        )
        return cast(dict[str, Any], result)

    def invoke(self, input: dict[str, Any]) -> dict[str, Any]:
        raise WorkflowConfigError("LoadTradingContextTool only supports async execution")


class LoadWatchlistTargetsTool:
    async def ainvoke(self, input: dict[str, Any]) -> dict[str, Any]:
        result = await WatchlistDecisionWorkflowService().load_watchlist_targets(
            context=input["context"],
        )
        return cast(dict[str, Any], result)

    def invoke(self, input: dict[str, Any]) -> dict[str, Any]:
        raise WorkflowConfigError("LoadWatchlistTargetsTool only supports async execution")


class SymbolSignalWorkerTool:
    async def ainvoke(self, input: dict[str, Any]) -> dict[str, Any]:
        result = await WatchlistDecisionWorkflowService().execute_symbol_signal(
            context=input["context"],
            target=input["target"],
            lookback_days=int(input.get("lookback_days") or 120),
        )
        return cast(dict[str, Any], result)

    def invoke(self, input: dict[str, Any]) -> dict[str, Any]:
        raise WorkflowConfigError("SymbolSignalWorkerTool only supports async execution")


class PersistTradingSignalsTool:
    async def ainvoke(self, input: dict[str, Any]) -> dict[str, Any]:
        result = await WatchlistDecisionWorkflowService().persist_trading_signals(
            context=input["context"],
            map_result=input["map_result"],
            node_id=str(input.get("node_id", "persist_trading_signals")),
            workflow_run_id=input.get("workflow_run_id") or None,
        )
        return cast(dict[str, Any], result)

    def invoke(self, input: dict[str, Any]) -> dict[str, Any]:
        raise WorkflowConfigError("PersistTradingSignalsTool only supports async execution")


class PortfolioSignalFusionTool:
    async def ainvoke(self, input: dict[str, Any]) -> dict[str, Any]:
        result = await WatchlistDecisionWorkflowService().fuse_portfolio_signals(
            context=input["context"],
            signal_result=input["signal_result"],
            node_id=str(input.get("node_id", "portfolio_signal_fusion")),
            min_confidence=float(input.get("min_confidence") or 0.6),
            max_selected=int(input.get("max_selected") or 10),
            workflow_run_id=input.get("workflow_run_id") or None,
        )
        return cast(dict[str, Any], result)

    def invoke(self, input: dict[str, Any]) -> dict[str, Any]:
        raise WorkflowConfigError("PortfolioSignalFusionTool only supports async execution")


class PositionSizingTool:
    @transactional(propagation=Propagation.NOT_SUPPORTED)
    async def ainvoke(self, input: dict[str, Any]) -> dict[str, Any]:
        result = await WatchlistDecisionWorkflowService().size_positions(
            context=input["context"],
            fusion_result=input["fusion_result"],
            node_id=str(input.get("node_id", "position_sizing")),
            workflow_run_id=input.get("workflow_run_id") or None,
        )
        return cast(dict[str, Any], result)

    def invoke(self, input: dict[str, Any]) -> dict[str, Any]:
        raise WorkflowConfigError("PositionSizingTool only supports async execution")


class RiskGatewayTool:
    async def ainvoke(self, input: dict[str, Any]) -> dict[str, Any]:
        result = await WatchlistDecisionWorkflowService().run_risk_gateway(
            context=input["context"],
            sizing_result=input["sizing_result"],
        )
        return cast(dict[str, Any], result)

    def invoke(self, input: dict[str, Any]) -> dict[str, Any]:
        raise WorkflowConfigError("RiskGatewayTool only supports async execution")


class GeneratePreOrdersTool:
    @transactional(propagation=Propagation.NOT_SUPPORTED)
    async def ainvoke(self, input: dict[str, Any]) -> dict[str, Any]:
        result = await WatchlistDecisionWorkflowService().generate_pre_orders(
            context=input["context"],
            risk_result=input["risk_result"],
            node_id=str(input.get("node_id", "generate_pre_orders")),
            workflow_run_id=input.get("workflow_run_id") or None,
        )
        return cast(dict[str, Any], result)

    def invoke(self, input: dict[str, Any]) -> dict[str, Any]:
        raise WorkflowConfigError("GeneratePreOrdersTool only supports async execution")
