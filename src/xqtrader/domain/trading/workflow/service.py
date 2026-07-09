"""盘后自选股决策工作流服务。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from math import floor, fsum
from typing import Any

import pandas as pd

from framework.commons.exceptions import WorkflowConfigError
from framework.commons.logger import get_logger
from framework.commons.time_util import now_shanghai
from framework.dal.transaction.transactional import transactional
from xqtrader.domain.factor.models.factor_value import FacFactorValue
from xqtrader.domain.factor.services.on_demand_compute_registry import get_registry
from xqtrader.domain.market.models.candlestick import CandlestickDaily
from xqtrader.domain.trading.backtest.core import RuleContext
from xqtrader.domain.trading.backtest.engine import SignalEngine
from xqtrader.domain.trading.enums import (
    ApprovalStatus,
    Direction,
    OrderType,
    PreOrderSide,
    PreOrderStatus,
    RiskEventType,
    RiskLevel,
    RuleDirection,
)
from xqtrader.domain.trading.loaders.strategy_loader import StrategyConfigLoader
from xqtrader.domain.trading.models.account import AccountSnapshot, TradingAccount
from xqtrader.domain.trading.models.decision import PositionSizingResult, SignalFusionResult, TradingSignal
from xqtrader.domain.trading.models.instance import StrategyInstance
from xqtrader.domain.trading.models.order import PreOrder
from xqtrader.domain.trading.models.position import PositionSnapshot
from xqtrader.domain.trading.models.risk import RiskEvent
from xqtrader.domain.trading.models.watchlist import Watchlist, WatchlistItem

logger = get_logger(__name__)
POSITION_WEIGHT_EPSILON = 1e-9
REBALANCE_WEIGHT_THRESHOLD = 0.03


@dataclass(frozen=True)
class WorkflowDates:
    signal_date: date
    execution_date: date


class WatchlistDecisionWorkflowService:
    """盘后自选股决策工作流服务。"""

    async def load_trading_context(
        self,
        instance_id: int,
        signal_date: str | date,
        execution_date: str | date | None = None,
    ) -> dict[str, Any]:
        dates = self._build_dates(signal_date, execution_date)
        instance = await StrategyInstance.get(instance_id)
        if instance is None:
            raise WorkflowConfigError(f"StrategyInstance not found: {instance_id}")

        account = await TradingAccount.get(instance.account_id)
        if account is None:
            raise WorkflowConfigError(f"TradingAccount not found: {instance.account_id}")
        if not account.is_enabled:
            raise WorkflowConfigError(f"TradingAccount disabled: {account.id}")

        snapshot = await AccountSnapshot.get_one_or_none(
            account_id=account.id,
            snapshot_date=dates.signal_date,
        )
        latest_position_row = await PositionSnapshot.filter(
            account_id=account.id,
            instance_id=instance_id,
            limit=1,
            order_by=PositionSnapshot.snapshot_date.desc(),
        )
        effective_snapshot_date = dates.signal_date
        if latest_position_row and latest_position_row[0].snapshot_date > dates.signal_date:
            effective_snapshot_date = latest_position_row[0].snapshot_date
            aligned_snapshot = await AccountSnapshot.get_one_or_none(
                account_id=account.id,
                snapshot_date=effective_snapshot_date,
            )
            if aligned_snapshot is None:
                logger.warning(
                    "决策流账户快照与持仓快照日期不一致 | account_id=%s signal_date=%s "
                    "effective_snapshot_date=%s 缺少 AccountSnapshot，回退 signal_date 快照",
                    account.id,
                    dates.signal_date,
                    effective_snapshot_date,
                )
            else:
                snapshot = aligned_snapshot
        positions = await PositionSnapshot.filter(
            account_id=account.id,
            instance_id=instance_id,
            snapshot_date=effective_snapshot_date,
            limit=None,
        )
        if not positions:
            positions = await self._load_latest_positions_on_or_before(
                account_id=account.id,
                instance_id=instance_id,
                snapshot_date=effective_snapshot_date,
            )

        active_positions = [position for position in positions if int(position.qty or 0) > 0]
        logger.info(
            "决策流加载交易上下文 | instance_id=%s account_id=%s signal_date=%s "
            "execution_date=%s effective_snapshot_date=%s total_assets=%s available_cash=%s positions=%s",
            instance_id,
            account.id,
            dates.signal_date,
            dates.execution_date,
            effective_snapshot_date,
            self._serialize_snapshot(snapshot, account).get("total_assets"),
            self._serialize_snapshot(snapshot, account).get("available_cash"),
            len(active_positions),
        )
        return {
            "instance_id": instance_id,
            "account_id": account.id,
            "signal_date": dates.signal_date.isoformat(),
            "execution_date": dates.execution_date.isoformat(),
            "instance": {
                "id": instance.id,
                "account_id": instance.account_id,
                "config": instance.config or {},
                "position_sizing": instance.position_sizing or {},
                "risk_overrides": instance.risk_overrides or {},
                "universe_pool": instance.universe_pool or "all",
            },
            "account": {
                "id": account.id,
                "available_cash": self._decimal_to_float(account.available_cash),
                "reduce_only": bool(account.reduce_only),
                "is_enabled": bool(account.is_enabled),
            },
            "account_snapshot": self._serialize_snapshot(snapshot, account),
            "positions": {
                position.symbol: self._serialize_position(position)
                for position in active_positions
            },
        }

    async def load_watchlist_targets(self, context: dict[str, Any]) -> dict[str, Any]:
        account_id = int(context["account_id"])
        instance_config = self._as_dict(context.get("instance", {}).get("config"))
        watchlist = await Watchlist.get_one_or_none(account_id=account_id)
        if watchlist is None:
            raise WorkflowConfigError(f"Watchlist not found for account: {account_id}")

        items = await WatchlistItem.filter(
            watchlist_id=watchlist.id,
            is_enabled=1,
            limit=None,
            order_by=WatchlistItem.sort_order.asc(),
        )
        targets: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for item in items:
            signal_config = self._as_dict(item.signal_config)
            strategy_id = signal_config.get("strategy_id")
            if not strategy_id:
                skipped.append({"symbol": item.symbol, "reason": "missing strategy_id"})
                continue
            targets.append({
                "symbol": item.symbol,
                "strategy_id": str(strategy_id),
                "signal_config": signal_config,
                "sizing_config": self._as_dict(item.sizing_config),
                "target_weight": self._watchlist_weight_to_fraction(item.target_weight),
                "fusion_weight": float(signal_config.get("fusion_weight", 1.0)),
                "pool_id": str(signal_config.get("pool_id") or instance_config.get("pool_id") or "all"),
            })

        logger.info(
            "决策流加载自选股 | account_id=%s watchlist_id=%s targets=%s skipped=%s symbols=%s",
            account_id,
            watchlist.id,
            len(targets),
            len(skipped),
            [target["symbol"] for target in targets],
        )
        return {
            "watchlist_id": watchlist.id,
            "targets": targets,
            "total": len(targets),
            "skipped": skipped,
        }

    async def execute_symbol_signal(
        self,
        context: dict[str, Any],
        target: dict[str, Any],
        lookback_days: int = 120,
    ) -> dict[str, Any]:
        symbol = str(target["symbol"])
        strategy_id = str(target["strategy_id"])
        signal_date = self._parse_date(context["signal_date"])
        strategy_config = await StrategyConfigLoader.load(strategy_id)
        all_factor_ids = strategy_config.get_all_factor_ids()
        # 因子分流：on_demand 因子由注册表实时计算（chan_*/td_seq_*/donchian_* 等，
        # §5.4 白名单），DB 因子从 FacFactorValue 加载。
        registry = get_registry()
        on_demand_factor_ids = sorted({
            fid for fid in all_factor_ids if registry.is_on_demand_factor(fid)
        })
        db_factor_ids = [fid for fid in all_factor_ids if fid not in on_demand_factor_ids]
        factor_values = await self._load_factor_values(
            symbol=symbol,
            signal_date=signal_date,
            pool_id=str(target.get("pool_id") or "all"),
            factor_ids=db_factor_ids,
            prev_factor_ids=strategy_config.get_all_prev_factor_ids(),
            lookback_days=lookback_days,
        )
        market_data = await self._load_entry_quote(symbol, signal_date)
        factor_values = factor_values | self._build_market_factor_values(market_data.get("bars", []))
        # on_demand 因子经 OnDemandComputeRegistry 实时计算（与 BacktestService 保持一致）
        if on_demand_factor_ids:
            on_demand_values = await self._compute_on_demand_factors(
                symbol=symbol,
                signal_date=signal_date,
                factor_ids=on_demand_factor_ids,
                lookback_days=lookback_days,
            )
            factor_values = factor_values | on_demand_values
        result = SignalEngine(strategy_config).execute(RuleContext(
            symbol=symbol,
            signal_date=signal_date,
            factor_values=factor_values,
            config=self._as_dict(target.get("signal_config")),
        ))
        direction = self._normalize_direction(result.direction)
        confidence = self._clamp(float(result.confidence))
        score = self._clamp(float(result.score))
        logger.info(
            "决策流标的信号 | symbol=%s strategy_id=%s direction=%s score=%.4f "
            "confidence=%.4f strength=%.4f passed=%s close=%s atr_14=%s reason=%s",
            symbol,
            strategy_id,
            direction,
            score,
            confidence,
            score * confidence,
            bool(result.passed),
            market_data.get("close"),
            self._calculate_atr(market_data.get("bars", [])),
            result.reason,
        )
        return {
            "symbol": symbol,
            "strategy_id": strategy_id,
            "signal_date": signal_date.isoformat(),
            "direction": direction,
            "score": score,
            "confidence": confidence,
            "strength": score * confidence,
            "reason": result.reason,
            "passed": bool(result.passed),
            "fusion_weight": float(target.get("fusion_weight", 1.0)),
            "target_weight": target.get("target_weight"),
            "sizing_config": self._as_dict(target.get("sizing_config")),
            "raw_values": {
                "rule_id": result.rule_id,
                "engine_direction": result.direction,
                "score": score,
                "confidence": confidence,
                "reason": result.reason,
                "detail": result.detail,
                "factor_values": factor_values,
                "market_data": {
                    "close": market_data.get("close"),
                    "atr_14": self._calculate_atr(market_data.get("bars", [])),
                },
            },
        }

    @transactional(bind_key="trading")
    async def persist_trading_signals(
        self,
        context: dict[str, Any],
        map_result: dict[str, Any],
        node_id: str,
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        instance_id = int(context["instance_id"])
        signal_date = self._parse_date(context["signal_date"])
        signals = self._extract_items(map_result)
        await TradingSignal.delete_many(
            instance_id=instance_id,
            signal_date=signal_date,
            node_id=node_id,
        )
        records = [
            TradingSignal(
                instance_id=instance_id,
                workflow_run_id=workflow_run_id,
                signal_date=signal_date,
                symbol=str(signal["symbol"]),
                direction=str(signal["direction"]),
                strength=float(signal.get("strength") or 0.0),
                signal_type="watchlist_signal",
                raw_values=self._as_dict(signal.get("raw_values")) | {
                    "strategy_id": signal.get("strategy_id"),
                    "confidence": signal.get("confidence"),
                },
                selection_id=None,
                node_id=node_id,
            )
            for signal in signals
        ]
        for record in records:
            await record.save()
        logger.info(
            "决策流信号持久化 | instance_id=%s signal_date=%s workflow_run_id=%s signals=%s persisted=%s directions=%s",
            instance_id,
            signal_date,
            workflow_run_id,
            len(signals),
            len(records),
            self._count_by_key(signals, "direction"),
        )
        return {"signals": signals, "persisted": len(records)}

    @transactional(bind_key="trading")
    async def fuse_portfolio_signals(
        self,
        context: dict[str, Any],
        signal_result: dict[str, Any],
        node_id: str,
        min_confidence: float = 0.6,
        max_selected: int = 10,
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        instance_id = int(context["instance_id"])
        signal_date = self._parse_date(context["signal_date"])
        signals = self._extract_signals(signal_result)
        candidates = [
            signal | {"fused_score": self._fused_score(signal)}
            for signal in signals
            if signal.get("direction") != Direction.NEUTRAL
            and float(signal.get("confidence") or 0.0) >= min_confidence
        ]
        selected = self._select_portfolio_signals(candidates, max_selected)

        await SignalFusionResult.delete_many(
            instance_id=instance_id,
            signal_date=signal_date,
            node_id=node_id,
        )
        for signal in selected:
            await SignalFusionResult.create(
                instance_id=instance_id,
                workflow_run_id=workflow_run_id,
                signal_date=signal_date,
                symbol=str(signal["symbol"]),
                direction=str(signal["direction"]),
                fused_score=float(signal["fused_score"]),
                contributing_signals={
                    "strategy_id": signal.get("strategy_id"),
                    "confidence": signal.get("confidence"),
                    "score": signal.get("score"),
                    "reason": signal.get("reason"),
                },
                node_id=node_id,
            )
        logger.info(
            "决策流组合信号融合 | instance_id=%s signal_date=%s workflow_run_id=%s "
            "raw_signals=%s candidates=%s selected=%s min_confidence=%.4f max_selected=%s "
            "directions=%s symbols=%s",
            instance_id,
            signal_date,
            workflow_run_id,
            len(signals),
            len(candidates),
            len(selected),
            min_confidence,
            max_selected,
            self._count_by_key(selected, "direction"),
            [
                {
                    "symbol": signal.get("symbol"),
                    "direction": signal.get("direction"),
                    "fused_score": round(float(signal.get("fused_score") or 0.0), 6),
                    "confidence": signal.get("confidence"),
                }
                for signal in selected
            ],
        )
        return {
            "selected_signals": selected,
            "total_candidates": len(candidates),
            "selected": len(selected),
            "min_confidence": min_confidence,
            "max_selected": max_selected,
        }

    async def size_positions(
        self,
        context: dict[str, Any],
        fusion_result: dict[str, Any],
        node_id: str,
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        instance_id = int(context["instance_id"])
        signal_date = self._parse_date(context["signal_date"])
        sizing_config = self._as_dict(context.get("instance", {}).get("position_sizing"))
        risk_config = self._as_dict(context.get("instance", {}).get("risk_overrides"))
        mode = str(sizing_config.get("mode", "equal_weight"))
        max_total_weight = float(sizing_config.get("max_total_weight", risk_config.get("max_total_weight", 1.0)))
        max_single_weight = float(sizing_config.get("max_single_weight", risk_config.get("max_single_weight", 0.2)))
        selected = self._extract_selected_signals(fusion_result)
        weight_candidates = [signal for signal in selected if signal.get("direction") != Direction.SHORT]
        weights = self._build_target_weights(weight_candidates, mode, max_total_weight, max_single_weight)
        results = await self._calculate_position_sizing_results(
            context=context,
            selected=selected,
            weights=weights,
            mode=mode,
            signal_date=signal_date,
        )

        await PositionSizingResult.delete_many(
            instance_id=instance_id,
            signal_date=signal_date,
            node_id=node_id,
        )
        for result in results:
            await PositionSizingResult.create(
                instance_id=instance_id,
                workflow_run_id=workflow_run_id,
                signal_date=signal_date,
                symbol=str(result["symbol"]),
                target_weight=float(result["target_weight"]),
                target_qty=result["target_qty"],
                current_weight=float(result["current_weight"]),
                sizing_strategy=mode,
                sizing_params=sizing_config,
                raw_score=float(result.get("raw_score") or 0.0),
                node_id=node_id,
            )
        logger.info(
            "决策流仓位管理 | instance_id=%s signal_date=%s workflow_run_id=%s mode=%s "
            "max_total_weight=%.6f max_single_weight=%.6f selected=%s long_candidates=%s "
            "sized=%s total_target_weight=%.6f details=%s",
            instance_id,
            signal_date,
            workflow_run_id,
            mode,
            max_total_weight,
            max_single_weight,
            len(selected),
            len(weight_candidates),
            len(results),
            sum(float(result.get("target_weight") or 0.0) for result in results),
            [
                {
                    "symbol": result.get("symbol"),
                    "direction": result.get("direction"),
                    "target_weight": round(float(result.get("target_weight") or 0.0), 6),
                    "current_weight": round(float(result.get("current_weight") or 0.0), 6),
                    "target_qty": result.get("target_qty"),
                    "market_price": result.get("market_price"),
                }
                for result in results
            ],
        )
        return {"sizing_results": results, "sized": len(results), "mode": mode}

    async def _calculate_position_sizing_results(
        self,
        context: dict[str, Any],
        selected: list[dict[str, Any]],
        weights: dict[str, float],
        mode: str,
        signal_date: date,
    ) -> list[dict[str, Any]]:
        account_snapshot = self._as_dict(context.get("account_snapshot"))
        total_assets = float(account_snapshot.get("total_assets") or 0.0)
        available_cash = float(account_snapshot.get("available_cash") or 0.0)
        remaining_cash = max(available_cash, 0.0)
        positions = self._as_dict(context.get("positions"))
        results: list[dict[str, Any]] = []
        for signal in selected:
            symbol = str(signal["symbol"])
            current_position = self._as_dict(positions.get(symbol))
            current_weight = float(current_position.get("weight") or 0.0)
            market_price = float(current_position.get("market_price") or 0.0)
            if market_price <= 0:
                market_price = await self._load_close_price(symbol, signal_date)
            target_weight = weights.get(symbol, 0.0)
            if signal.get("direction") == Direction.SHORT:
                target_weight = 0.0
            target_qty = self._calculate_target_qty(
                total_assets=total_assets,
                available_cash=remaining_cash,
                target_weight=target_weight,
                current_weight=current_weight,
                market_price=market_price,
            )
            remaining_cash -= self._calculate_incremental_cash_required(
                total_assets=total_assets,
                current_weight=current_weight,
                market_price=market_price,
                target_qty=target_qty,
            )
            remaining_cash = max(remaining_cash, 0.0)
            results.append({
                "symbol": symbol,
                "direction": signal.get("direction"),
                "target_weight": target_weight,
                "current_weight": current_weight,
                "current_qty": int(current_position.get("qty") or 0),
                "available_qty": int(current_position.get("available_qty") or 0),
                "market_price": market_price,
                "target_qty": target_qty,
                "sizing_strategy": mode,
                "raw_score": signal.get("fused_score"),
                "signal": signal,
            })
        return results

    async def _resolve_blocking_risk_events(
        self,
        account_id: int,
        instance_id: int,
        symbol: str | None,
        resolved_by: str,
    ) -> None:
        filters: dict[str, Any] = {
            "account_id": account_id,
            "instance_id": instance_id,
            "event_type": RiskEventType.BLOCKED,
            "resolved": False,
        }
        if symbol is None:
            filters["action_taken"] = "all_pre_orders_blocked"
        else:
            filters["action_taken"] = "pre_order_blocked"
        events = await RiskEvent.filter(limit=None, **filters)
        now = now_shanghai()
        for event in events:
            detail = self._as_dict(event.detail)
            if symbol is not None and detail.get("symbol") != symbol:
                continue
            await event.update({"resolved": True, "resolved_by": resolved_by, "resolved_at": now})

    @transactional(bind_key="trading")
    async def run_risk_gateway(
        self,
        context: dict[str, Any],
        sizing_result: dict[str, Any],
    ) -> dict[str, Any]:
        risk_config = self._as_dict(context.get("instance", {}).get("risk_overrides"))
        sizing_config = self._as_dict(context.get("instance", {}).get("position_sizing"))
        account = self._as_dict(context.get("account"))
        account_id = int(context["account_id"])
        instance_id = int(context["instance_id"])
        max_single_weight = float(risk_config.get("max_single_weight", sizing_config.get("max_single_weight", 0.2)))
        max_total_weight = float(risk_config.get("max_total_weight", sizing_config.get("max_total_weight", 1.0)))
        blacklist = {str(symbol) for symbol in risk_config.get("blacklist", [])}
        reduce_only = bool(account.get("reduce_only", False))
        results = self._extract_sizing_results(sizing_result)

        approved: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        approved_weights: list[float] = []
        for result in results:
            reasons: list[str] = []
            symbol = str(result["symbol"])
            target_weight = float(result.get("target_weight") or 0.0)
            current_weight = float(result.get("current_weight") or 0.0)
            if symbol in blacklist:
                reasons.append("blacklisted")
            if target_weight - max_single_weight > POSITION_WEIGHT_EPSILON:
                reasons.append("max_single_weight_exceeded")
            if reduce_only and target_weight - current_weight > POSITION_WEIGHT_EPSILON:
                reasons.append("account_reduce_only")
            checked = result | {"risk_check_passed": not reasons, "risk_check_detail": {"reasons": reasons}}
            logger.info(
                "决策流风控逐标的 | account_id=%s instance_id=%s symbol=%s direction=%s "
                "target_weight=%.12f current_weight=%.12f target_qty=%s "
                "max_single_weight=%.12f reduce_only=%s passed=%s reasons=%s",
                account_id,
                instance_id,
                symbol,
                result.get("direction"),
                target_weight,
                current_weight,
                result.get("target_qty"),
                max_single_weight,
                reduce_only,
                not reasons,
                reasons,
            )
            if reasons:
                await RiskEvent.create(
                    account_id=account_id,
                    instance_id=instance_id,
                    event_type=RiskEventType.BLOCKED,
                    level=RiskLevel.WARN,
                    detail={"symbol": symbol, "reasons": reasons, "target_weight": target_weight},
                    action_taken="pre_order_blocked",
                    resolved=False,
                )
                rejected.append(checked)
            else:
                approved_weights.append(min(target_weight, max_single_weight))
                await self._resolve_blocking_risk_events(
                    account_id=account_id,
                    instance_id=instance_id,
                    symbol=symbol,
                    resolved_by="risk_gateway_passed",
                )
                approved.append(checked)

        total_weight = self._normalize_weight(fsum(approved_weights))
        if total_weight - max_total_weight > POSITION_WEIGHT_EPSILON:
            await RiskEvent.create(
                account_id=account_id,
                instance_id=instance_id,
                event_type=RiskEventType.BLOCKED,
                level=RiskLevel.CRITICAL,
                detail={"reasons": ["max_total_weight_exceeded"], "total_weight": total_weight},
                action_taken="all_pre_orders_blocked",
                resolved=False,
            )
            for result in approved:
                result["risk_check_passed"] = False
                result["risk_check_detail"] = {"reasons": ["max_total_weight_exceeded"]}
            rejected.extend(approved)
            approved = []
        else:
            await self._resolve_blocking_risk_events(
                account_id=account_id,
                instance_id=instance_id,
                symbol=None,
                resolved_by="risk_gateway_passed",
            )

        logger.info(
            "决策流风控汇总 | account_id=%s instance_id=%s total_weight=%.12f "
            "max_total_weight=%.12f approved=%s rejected=%s reject_reasons=%s",
            account_id,
            instance_id,
            total_weight,
            max_total_weight,
            len(approved),
            len(rejected),
            self._collect_reject_reasons(rejected),
        )
        return {
            "approved": approved,
            "rejected": rejected,
            "total_weight": total_weight,
            "risk_config": risk_config,
        }

    async def generate_pre_orders(
        self,
        context: dict[str, Any],
        risk_result: dict[str, Any],
        node_id: str,
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        instance_id = int(context["instance_id"])
        signal_date = self._parse_date(context["signal_date"])
        execution_date = self._parse_date(context["execution_date"])
        approved = self._extract_approved(risk_result)
        now = now_shanghai()
        await PreOrder.update_by(
            {
                "status": PreOrderStatus.EXPIRED,
                "approval_status": ApprovalStatus.EXPIRED,
                "expired_at": now,
            },
            instance_id=instance_id,
            approval_status=ApprovalStatus.PENDING,
        )
        pre_orders: list[PreOrder] = []
        skipped: list[dict[str, Any]] = []
        for item in approved:
            side = self._build_pre_order_side(item)
            if side is None:
                skipped.append({
                    "symbol": item.get("symbol"),
                    "reason": "no_position_to_reduce",
                    "direction": item.get("direction"),
                    "current_weight": item.get("current_weight"),
                    "current_qty": item.get("current_qty"),
                })
                logger.info(
                    "决策流跳过预订单 | instance_id=%s symbol=%s direction=%s reason=%s "
                    "current_weight=%s current_qty=%s",
                    instance_id,
                    item.get("symbol"),
                    item.get("direction"),
                    "no_position_to_reduce",
                    item.get("current_weight"),
                    item.get("current_qty"),
                )
                continue
            item["target_qty"] = self._build_pre_order_target_qty(item, side)
            if not self._should_create_pre_order(item, side):
                skipped.append({
                    "symbol": item.get("symbol"),
                    "reason": "rebalance_not_needed",
                    "direction": item.get("direction"),
                    "current_weight": item.get("current_weight"),
                    "target_weight": item.get("target_weight"),
                    "target_qty": item.get("target_qty"),
                })
                logger.info(
                    "决策流跳过预订单 | instance_id=%s symbol=%s side=%s reason=rebalance_not_needed "
                    "target_weight=%s current_weight=%s target_qty=%s",
                    instance_id,
                    item.get("symbol"),
                    side,
                    item.get("target_weight"),
                    item.get("current_weight"),
                    item.get("target_qty"),
                )
                continue
            limit_price = await self._build_entry_limit_price(item, signal_date)
            logger.info(
                "决策流生成预订单逐标的 | instance_id=%s symbol=%s side=%s "
                "target_weight=%.6f current_weight=%.6f target_qty=%s limit_price=%s "
                "entry_price_detail=%s",
                instance_id,
                item.get("symbol"),
                side,
                float(item.get("target_weight") or 0.0),
                float(item.get("current_weight") or 0.0),
                item.get("target_qty"),
                limit_price,
                item.get("entry_price_detail"),
            )
            pre_orders.append(PreOrder(
                instance_id=instance_id,
                workflow_run_id=workflow_run_id,
                signal_date=signal_date,
                execution_date=execution_date,
                symbol=str(item["symbol"]),
                side=side,
                target_weight=float(item.get("target_weight") or 0.0),
                current_weight=float(item.get("current_weight") or 0.0),
                target_qty=item.get("target_qty"),
                order_type=OrderType.LIMIT,
                limit_price=limit_price,
                sizing_strategy=item.get("sizing_strategy"),
                status=PreOrderStatus.PENDING_APPROVAL,
                risk_check_passed=True,
                risk_check_detail=self._as_dict(item.get("risk_check_detail")) | {
                    "entry_price_detail": item.get("entry_price_detail"),
                    "current_qty": item.get("current_qty"),
                    "available_qty": item.get("available_qty"),
                },
                approval_status=ApprovalStatus.PENDING,
                approved_by=None,
                approved_at=None,
                approval_comment=None,
                expired_at=None,
                idempotency_key=f"{instance_id}:{signal_date.isoformat()}:{item['symbol']}",
                node_id=node_id,
            ))

        persisted = await PreOrder.bulk_create_or_update(
            pre_orders,
            on_conflict=["idempotency_key"],
            update_fields=[
                "workflow_run_id",
                "execution_date",
                "target_weight",
                "current_weight",
                "target_qty",
                "sizing_strategy",
                "status",
                "risk_check_passed",
                "risk_check_detail",
                "approval_status",
                "approved_by",
                "approved_at",
                "approval_comment",
                "expired_at",
                "limit_price",
                "side",
                "node_id",
            ],
        )
        logger.info(
            "决策流预订单汇总 | instance_id=%s signal_date=%s workflow_run_id=%s "
            "approved_inputs=%s created=%s skipped=%s rejected=%s skipped_detail=%s "
            "rejected_reasons=%s",
            instance_id,
            signal_date,
            workflow_run_id,
            len(approved),
            persisted,
            len(skipped),
            len(risk_result.get("rejected", [])),
            skipped,
            self._collect_reject_reasons(risk_result.get("rejected", [])),
        )
        return {
            "pre_orders": [self._serialize_pre_order(item) for item in pre_orders],
            "created": persisted,
            "rejected": risk_result.get("rejected", []),
            "skipped": skipped,
        }

    async def _build_entry_limit_price(self, item: dict[str, Any], signal_date: date) -> Decimal | None:
        quote = await self._load_entry_quote(str(item["symbol"]), signal_date)
        close_value = quote.get("close")
        close_price = (
            float(close_value)
            if close_value is not None
            else float(item.get("market_price") or 0.0)
        )
        if close_price <= 0:
            return None
        atr = self._calculate_atr(quote.get("bars", []))
        buffer_ratio = min(
            0.02,
            max(0.003, (atr / close_price * 0.2) if atr > 0 else 0.005),
        )
        side = self._build_pre_order_side(item)
        if side in {PreOrderSide.OPEN, PreOrderSide.ADD}:
            price = close_price * (1 + buffer_ratio)
        else:
            price = close_price * (1 - buffer_ratio)
        item["entry_price_detail"] = {
            "method": "atr_limit_buffer",
            "close": round(close_price, 4),
            "atr_14": round(atr, 4) if atr > 0 else None,
            "buffer_ratio": round(buffer_ratio, 6),
            "side": side,
        }
        return Decimal(str(round(price, 4)))

    async def _load_entry_quote(self, symbol: str, signal_date: date) -> dict[str, Any]:
        bars = await CandlestickDaily.filter(
            symbol=symbol,
            trade_date__lte=signal_date,
            limit=21,
            order_by=CandlestickDaily.trade_date.desc(),
        )
        if not bars:
            return {"close": 0.0, "bars": []}
        ordered = sorted(bars, key=lambda row: row.trade_date)
        return {"close": float(ordered[-1].close), "bars": ordered}

    async def _load_close_price(self, symbol: str, signal_date: date) -> float:
        quote = await self._load_entry_quote(symbol, signal_date)
        return float(quote.get("close") or 0.0)

    @staticmethod
    def _calculate_atr(bars: list[CandlestickDaily]) -> float:
        if len(bars) < 2:
            return 0.0
        true_ranges: list[float] = []
        previous_close = float(bars[0].close)
        for bar in bars[1:]:
            high = float(bar.high)
            low = float(bar.low)
            true_ranges.append(max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            ))
            previous_close = float(bar.close)
        if not true_ranges:
            return 0.0
        return sum(true_ranges) / len(true_ranges)

    @classmethod
    def _build_market_factor_values(cls, bars: list[CandlestickDaily]) -> dict[str, float | None]:
        if not bars:
            return {}
        close = float(bars[-1].close)
        channel_bars = bars[:-1] or bars
        highs = [float(bar.high) for bar in channel_bars[-20:]]
        lows = [float(bar.low) for bar in channel_bars[-10:]]
        return {
            "close": close,
            "atr_14": cls._calculate_atr(bars),
            "donchian_high_20": max(highs) if highs else None,
            "donchian_low_10": min(lows) if lows else None,
        }

    async def _compute_on_demand_factors(
        self,
        symbol: str,
        signal_date: date,
        factor_ids: list[str],
        lookback_days: int,
    ) -> dict[str, float | None]:
        """经 OnDemandComputeRegistry 实时计算 on_demand 因子（signal_date 当天的值）。

        与 BacktestService._load_data 保持一致：加载 OHLCV -> compute_factors ->
        取目标日期的因子值。预热期使用 lookback_days*2 日历日（约 lookback_days 个交易日），
        与 BacktestService 的 warmup_days*2 算法对齐，确保 EMA 类指标结果一致。
        """
        registry = get_registry()
        if not factor_ids or not registry.list_on_demand_factors():
            return {fid: None for fid in factor_ids}
        warmup_start = signal_date - timedelta(days=lookback_days * 2)
        bars = await CandlestickDaily.filter(
            symbol=symbol,
            trade_date__gte=warmup_start,
            trade_date__lte=signal_date,
            limit=None,
            order_by=CandlestickDaily.trade_date.asc(),
        )
        if not bars:
            return {fid: None for fid in factor_ids}
        ohlcv_df = pd.DataFrame([
            {
                "trade_date": pd.Timestamp(b.trade_date),
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": int(b.volume),
            }
            for b in bars
        ]).set_index("trade_date")
        computed = registry.compute_factors(ohlcv_df, sorted(factor_ids))
        signal_ts = pd.Timestamp(signal_date)
        result: dict[str, float | None] = {}
        for fid in factor_ids:
            if fid not in computed.columns or signal_ts not in computed.index:
                result[fid] = None
                continue
            val = computed.loc[signal_ts, fid]
            if val is None or pd.isna(val):
                result[fid] = None
            else:
                result[fid] = float(val)  # type: ignore[arg-type]
        return result

    async def _load_factor_values(
        self,
        symbol: str,
        signal_date: date,
        pool_id: str,
        factor_ids: list[str],
        prev_factor_ids: list[str],
        lookback_days: int,
    ) -> dict[str, float | None]:
        all_factor_ids = sorted(set(factor_ids) | set(prev_factor_ids))
        if not all_factor_ids:
            return {}
        start_date = signal_date - timedelta(days=lookback_days)
        records = await FacFactorValue.filter(
            symbol=symbol,
            pool_id=pool_id,
            factor_id__in=all_factor_ids,
            trade_date__gte=start_date,
            trade_date__lte=signal_date,
            limit=None,
            order_by=[FacFactorValue.factor_id.asc(), FacFactorValue.trade_date.desc()],
        )
        current_values: dict[str, float | None] = {}
        prev_values: dict[str, float | None] = {}
        for record in records:
            if (
                record.factor_id in factor_ids
                and record.trade_date == signal_date
                and record.factor_id not in current_values
            ):
                current_values[record.factor_id] = record.factor_value
            prev_key = f"{record.factor_id}_prev"
            if (
                record.factor_id in prev_factor_ids
                and record.trade_date < signal_date
                and prev_key not in prev_values
            ):
                prev_values[prev_key] = record.factor_value
        return current_values | prev_values

    @staticmethod
    def _build_dates(signal_date: str | date, execution_date: str | date | None) -> WorkflowDates:
        parsed_signal_date = WatchlistDecisionWorkflowService._parse_date(signal_date)
        parsed_execution_date = (
            WatchlistDecisionWorkflowService._parse_date(execution_date)
            if execution_date is not None
            else parsed_signal_date + timedelta(days=1)
        )
        return WorkflowDates(signal_date=parsed_signal_date, execution_date=parsed_execution_date)

    @staticmethod
    def _parse_date(value: str | date) -> date:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        return date.fromisoformat(value)

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _decimal_to_float(value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return float(value)
        return float(value)

    @staticmethod
    def _watchlist_weight_to_fraction(value: Any) -> float | None:
        weight = WatchlistDecisionWorkflowService._decimal_to_float(value)
        if weight is None:
            return None
        if weight > 1:
            return weight / 100
        return weight

    @staticmethod
    async def _load_latest_positions_on_or_before(
        account_id: int,
        instance_id: int,
        snapshot_date: date,
    ) -> list[PositionSnapshot]:
        from sqlalchemy import and_, func, select

        subq = (
            select(
                PositionSnapshot.symbol,
                func.max(PositionSnapshot.snapshot_date).label("max_snapshot_date"),
            )
            .where(
                PositionSnapshot.account_id == account_id,
                PositionSnapshot.instance_id == instance_id,
                PositionSnapshot.snapshot_date <= snapshot_date,
            )
            .group_by(PositionSnapshot.symbol)
            .subquery()
        )
        stmt = select(PositionSnapshot).join(
            subq,
            and_(
                PositionSnapshot.symbol == subq.c.symbol,
                PositionSnapshot.snapshot_date == subq.c.max_snapshot_date,
                PositionSnapshot.account_id == account_id,
                PositionSnapshot.instance_id == instance_id,
            ),
        )

        async with PositionSnapshot._get_engines_manager().get_transaction_session(
            PositionSnapshot._get_bind_key(),
        ) as db:
            result = await db.execute(stmt)
            return list(result.scalars().all())

    @staticmethod
    def _serialize_snapshot(snapshot: AccountSnapshot | None, account: TradingAccount) -> dict[str, Any]:
        if snapshot is None:
            return {
                "total_assets": WatchlistDecisionWorkflowService._decimal_to_float(account.initial_capital) or 0.0,
                "available_cash": WatchlistDecisionWorkflowService._decimal_to_float(account.available_cash) or 0.0,
            }
        return {
            "total_assets": WatchlistDecisionWorkflowService._decimal_to_float(snapshot.total_assets) or 0.0,
            "market_value": WatchlistDecisionWorkflowService._decimal_to_float(snapshot.market_value) or 0.0,
            "available_cash": WatchlistDecisionWorkflowService._decimal_to_float(snapshot.available_cash) or 0.0,
            "frozen_cash": WatchlistDecisionWorkflowService._decimal_to_float(snapshot.frozen_cash) or 0.0,
        }

    @staticmethod
    def _serialize_position(position: PositionSnapshot) -> dict[str, Any]:
        return {
            "qty": position.qty,
            "available_qty": position.available_qty,
            "market_price": WatchlistDecisionWorkflowService._decimal_to_float(position.market_price),
            "market_value": WatchlistDecisionWorkflowService._decimal_to_float(position.market_value),
            "weight": WatchlistDecisionWorkflowService._decimal_to_float(position.weight) or 0.0,
        }

    @staticmethod
    def _normalize_direction(direction: str) -> str:
        if direction in {RuleDirection.BUY, RuleDirection.BULLISH, Direction.LONG}:
            return Direction.LONG
        if direction in {RuleDirection.SELL, RuleDirection.BEARISH, Direction.SHORT}:
            return Direction.SHORT
        return Direction.NEUTRAL

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))

    @staticmethod
    def _extract_items(map_result: dict[str, Any]) -> list[dict[str, Any]]:
        items = map_result.get("items", [])
        return [item for item in items if isinstance(item, dict)]

    @staticmethod
    def _extract_signals(signal_result: dict[str, Any]) -> list[dict[str, Any]]:
        signals = signal_result.get("signals", [])
        return [signal for signal in signals if isinstance(signal, dict)]

    @staticmethod
    def _extract_selected_signals(fusion_result: dict[str, Any]) -> list[dict[str, Any]]:
        signals = fusion_result.get("selected_signals", [])
        return [signal for signal in signals if isinstance(signal, dict)]

    @staticmethod
    def _extract_sizing_results(sizing_result: dict[str, Any]) -> list[dict[str, Any]]:
        results = sizing_result.get("sizing_results", [])
        return [result for result in results if isinstance(result, dict)]

    @staticmethod
    def _extract_approved(risk_result: dict[str, Any]) -> list[dict[str, Any]]:
        approved = risk_result.get("approved", [])
        return [item for item in approved if isinstance(item, dict)]

    @staticmethod
    def _count_by_key(items: list[dict[str, Any]], key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            value = str(item.get(key) or "unknown")
            counts[value] = counts.get(value, 0) + 1
        return counts

    @staticmethod
    def _collect_reject_reasons(items: Any) -> dict[str, int]:
        if not isinstance(items, list):
            return {}
        reasons: dict[str, int] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            detail = item.get("risk_check_detail")
            if not isinstance(detail, dict):
                continue
            item_reasons = detail.get("reasons")
            if not isinstance(item_reasons, list):
                continue
            for reason in item_reasons:
                reason_key = str(reason)
                reasons[reason_key] = reasons.get(reason_key, 0) + 1
        return reasons

    @staticmethod
    def _fused_score(signal: dict[str, Any]) -> float:
        return (
            float(signal.get("score") or 0.0)
            * float(signal.get("confidence") or 0.0)
            * float(signal.get("fusion_weight") or 1.0)
        )

    @staticmethod
    def _select_portfolio_signals(candidates: list[dict[str, Any]], max_selected: int) -> list[dict[str, Any]]:
        best_by_symbol: dict[str, dict[str, Any]] = {}
        for signal in candidates:
            symbol = str(signal["symbol"])
            current = best_by_symbol.get(symbol)
            if current is None or float(signal["fused_score"]) > float(current["fused_score"]):
                best_by_symbol[symbol] = signal
        return sorted(best_by_symbol.values(), key=lambda item: float(item["fused_score"]), reverse=True)[:max_selected]

    @staticmethod
    def _build_target_weights(
        selected: list[dict[str, Any]],
        mode: str,
        max_total_weight: float,
        max_single_weight: float = 1.0,
    ) -> dict[str, float]:
        if not selected:
            return {}
        if mode == "watchlist_target_weight":
            missing_weight_symbols = [
                str(signal["symbol"])
                for signal in selected
                if signal.get("target_weight") is None
            ]
            if missing_weight_symbols:
                raise WorkflowConfigError(
                    "自选股目标权重未配置: " + ", ".join(missing_weight_symbols),
                )
            weights = {
                str(signal["symbol"]): min(float(signal["target_weight"]), max_single_weight)
                for signal in selected
            }
            return WatchlistDecisionWorkflowService._scale_target_weights(weights, max_total_weight)
        if mode == "confidence_weighted":
            total_confidence = sum(float(signal.get("confidence") or 0.0) for signal in selected)
            if total_confidence > 0:
                return {
                    str(signal["symbol"]): min(
                        max_total_weight * float(signal.get("confidence") or 0.0) / total_confidence,
                        max_single_weight,
                    )
                    for signal in selected
                }
        equal_weight = min(max_total_weight / len(selected), max_single_weight)
        return {str(signal["symbol"]): equal_weight for signal in selected}

    @staticmethod
    def _normalize_weight(weight: float) -> float:
        return round(weight, 12)

    @staticmethod
    def _scale_target_weights(weights: dict[str, float], max_total_weight: float) -> dict[str, float]:
        total_weight = sum(max(0.0, weight) for weight in weights.values())
        if total_weight <= 0:
            return {symbol: 0.0 for symbol in weights}
        if total_weight <= max_total_weight:
            return {symbol: max(0.0, weight) for symbol, weight in weights.items()}
        scale = max_total_weight / total_weight
        return {symbol: max(0.0, weight) * scale for symbol, weight in weights.items()}

    @staticmethod
    def _calculate_target_qty(
        total_assets: float,
        available_cash: float,
        target_weight: float,
        current_weight: float,
        market_price: float,
    ) -> int | None:
        if total_assets <= 0 or target_weight <= 0 or market_price <= 0:
            return None
        target_value = total_assets * target_weight
        current_value = total_assets * max(current_weight, 0.0)
        required_cash = max(0.0, target_value - current_value)
        if required_cash > available_cash:
            target_value = current_value + max(available_cash, 0.0)
        qty = floor((target_value / market_price) / 100) * 100
        return qty if qty > 0 else None

    @staticmethod
    def _calculate_incremental_cash_required(
        total_assets: float,
        current_weight: float,
        market_price: float,
        target_qty: int | None,
    ) -> float:
        if total_assets <= 0 or market_price <= 0 or target_qty is None:
            return 0.0
        target_value = target_qty * market_price
        current_value = total_assets * max(current_weight, 0.0)
        return max(0.0, target_value - current_value)

    @staticmethod
    def _should_create_pre_order(item: dict[str, Any], side: str) -> bool:
        target_qty = item.get("target_qty")
        if target_qty is None or int(target_qty) <= 0:
            return False
        if side == PreOrderSide.CLOSE:
            return True
        target_weight = float(item.get("target_weight") or 0.0)
        current_weight = float(item.get("current_weight") or 0.0)
        return abs(target_weight - current_weight) > REBALANCE_WEIGHT_THRESHOLD

    @staticmethod
    def _build_pre_order_side(item: dict[str, Any]) -> str | None:
        target_weight = float(item.get("target_weight") or 0.0)
        current_weight = float(item.get("current_weight") or 0.0)
        current_qty = int(item.get("current_qty") or 0)
        has_position = current_weight > 0 or current_qty > 0
        if target_weight <= 0:
            return PreOrderSide.CLOSE if has_position else None
        if has_position and target_weight < current_weight:
            return PreOrderSide.REDUCE
        return PreOrderSide.ADD if has_position else PreOrderSide.OPEN

    @staticmethod
    def _build_pre_order_target_qty(item: dict[str, Any], side: str) -> int | None:
        if side == PreOrderSide.CLOSE:
            current_qty = int(item.get("available_qty") or item.get("current_qty") or 0)
            return current_qty if current_qty > 0 else None
        if side == PreOrderSide.REDUCE:
            current_qty = int(item.get("current_qty") or 0)
            target_qty = int(item.get("target_qty") or 0)
            reduce_qty = current_qty - target_qty
            return reduce_qty if reduce_qty > 0 else None
        if side == PreOrderSide.ADD:
            current_qty = int(item.get("current_qty") or 0)
            absolute_target = int(item.get("target_qty") or 0)
            add_qty = absolute_target - current_qty
            add_qty = (add_qty // 100) * 100
            return add_qty if add_qty > 0 else None
        return item.get("target_qty")

    @staticmethod
    def _serialize_pre_order(pre_order: PreOrder) -> dict[str, Any]:
        return {
            "symbol": pre_order.symbol,
            "side": pre_order.side,
            "signal_date": pre_order.signal_date.isoformat(),
            "execution_date": pre_order.execution_date.isoformat(),
            "target_weight": pre_order.target_weight,
            "current_weight": pre_order.current_weight,
            "target_qty": pre_order.target_qty,
            "limit_price": float(pre_order.limit_price) if pre_order.limit_price is not None else None,
            "status": pre_order.status,
            "approval_status": pre_order.approval_status,
            "idempotency_key": pre_order.idempotency_key,
        }
