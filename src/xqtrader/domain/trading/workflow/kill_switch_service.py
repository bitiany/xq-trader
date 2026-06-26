"""账户紧急全平服务 — 绕过审批直连 Broker。

设计要点：
1. 事务内：reduce_only、风控事件、close 预订单/订单创建、SUBMITTED 订单乐观标记 CANCELLED
2. 事务外：调用 QMT 撤单、提交 close 订单（模拟撮合或实盘 QMT）
3. 撤单失败由结果集汇总返回；不阻塞主流程
"""
from __future__ import annotations

import threading
from typing import Any
from uuid import uuid4

from framework.commons.exceptions import BusinessException, NotFoundException
from framework.commons.logger import get_logger
from framework.commons.time_util import now_shanghai, today_shanghai
from framework.dal.transaction import transactional
from xqtrader.broker.services.qmt_trader import QmtTrader
from xqtrader.domain.trading.enums import (
    AccountType,
    ApprovalStatus,
    BrokerType,
    OrderEventType,
    OrderSide,
    OrderStatus,
    OrderType,
    PreOrderSide,
    PreOrderStatus,
    RiskEventType,
    RiskLevel,
)
from xqtrader.domain.trading.models.account import TradingAccount
from xqtrader.domain.trading.models.instance import StrategyInstance
from xqtrader.domain.trading.models.order import Order, OrderEvent, PreOrder
from xqtrader.domain.trading.models.position import PositionSnapshot
from xqtrader.domain.trading.models.risk import RiskEvent
from xqtrader.domain.trading.workflow.execution_service import (
    PreOrderExecutionWorkflowService,
)
from xqtrader.domain.trading.workflow.simulated_matching_service import (
    SimulatedMatchingService,
)

logger = get_logger(__name__)


class KillSwitchService:
    """账户紧急全平服务（单例）：reduce_only + 取消挂单 + 平仓所有持仓。"""

    _instance: KillSwitchService | None = None
    _instance_lock = threading.Lock()
    _qmt_trader: QmtTrader | None = None
    _execution_service: PreOrderExecutionWorkflowService | None = None
    _matching_service: SimulatedMatchingService | None = None

    @classmethod
    def get_instance(cls) -> KillSwitchService:
        """获取单例实例。"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @property
    def qmt_trader(self) -> QmtTrader:
        if self._qmt_trader is None:
            self._qmt_trader = QmtTrader()
        return self._qmt_trader

    @property
    def execution_service(self) -> PreOrderExecutionWorkflowService:
        if self._execution_service is None:
            self._execution_service = PreOrderExecutionWorkflowService()
        return self._execution_service

    @property
    def matching_service(self) -> SimulatedMatchingService:
        # 延迟创建并持有 execution_service 引用，确保共享同一 PreOrderExecutionWorkflowService
        # （内部 _qmt_trader 类属性缓存，避免重复创建 QmtTrader 连接）。
        if self._matching_service is None:
            self._matching_service = SimulatedMatchingService(self.execution_service)
        return self._matching_service

    async def execute(
        self,
        account_id: int,
        operator: str,
        reason: str,
    ) -> dict[str, Any]:
        """执行紧急全平流程。

        Args:
            account_id: 交易账户 ID
            operator: 操作人
            reason: 触发原因（写入风控事件与订单事件）

        Returns:
            汇总结果：reduce_only 标记、风控事件 ID、撤单与平仓订单列表
        """
        account = await self._validate_account(account_id)
        close_order_ids, cancel_specs = await self._prepare_kill_switch(
            account_id=account_id,
            account=account,
            operator=operator,
            reason=reason,
        )
        cancel_results = await self._cancel_submitted_orders(cancel_specs)
        submit_results = await self._submit_close_orders(
            account=account,
            order_ids=close_order_ids,
            operator=operator,
        )
        return {
            "account_id": account_id,
            "reduce_only": True,
            "cancelled_orders": cancel_results,
            "close_orders": submit_results,
        }

    async def _validate_account(self, account_id: int) -> TradingAccount:
        account = await TradingAccount.get_or_none(id=account_id)
        if account is None:
            raise NotFoundException(message=f"账户不存在: {account_id}")
        if account.account_type not in (AccountType.LIVE, AccountType.PAPER):
            raise BusinessException(message=f"账户类型不合法: {account.account_type}")
        # reduce_only 去重（防重复触发）：已处于紧急全平状态的账户不应再次触发，
        # 否则会重复创建 close 订单（idempotency_key 跨天失效后尤甚）。
        # 如需重试未平仓持仓，应先重置 reduce_only 后再触发。
        if account.reduce_only:
            raise BusinessException(
                message=f"账户已处于紧急全平状态(reduce_only=True)，请勿重复触发: {account_id}",
            )
        return account

    @transactional(bind_key="trading")
    async def _prepare_kill_switch(
        self,
        account_id: int,
        account: TradingAccount,
        operator: str,
        reason: str,
    ) -> tuple[list[int], list[dict[str, Any]]]:
        """事务内：reduce_only + 风控事件 + 取消挂单 + 创建 close 订单。"""
        await account.update({"reduce_only": True})
        await RiskEvent.create(
            account_id=account_id,
            event_type=RiskEventType.KILL_SWITCH,
            level=RiskLevel.FATAL,
            detail={"reason": reason, "operator": operator},
            action_taken="reduce_only_and_close_orders_submitted",
            resolved=False,
        )
        cancel_specs = await self._mark_submitted_orders_cancelled(account_id, operator)
        close_order_ids = await self._create_close_orders_for_positions(
            account_id=account_id,
            operator=operator,
            reason=reason,
        )
        return close_order_ids, cancel_specs

    async def _mark_submitted_orders_cancelled(
        self,
        account_id: int,
        operator: str,
    ) -> list[dict[str, Any]]:
        """乐观标记所有 SUBMITTED 订单为 CANCELLED，收集 broker_order_id 供事务外撤单。"""
        submitted_orders = await Order.filter(
            account_id=account_id,
            status=OrderStatus.SUBMITTED,
            limit=None,
        )
        specs: list[dict[str, Any]] = []
        for order in submitted_orders:
            await order.update({"status": OrderStatus.CANCELLED})
            await OrderEvent.create(
                order_id=order.id,
                event_type=OrderEventType.CANCELLED,
                event_data={"reason": "kill_switch", "operator": operator},
                operator=operator,
            )
            if order.broker_order_id:
                specs.append({
                    "order_id": order.id,
                    "broker_order_id": order.broker_order_id,
                })
        return specs

    async def _create_close_orders_for_positions(
        self,
        account_id: int,
        operator: str,
        reason: str,
    ) -> list[int]:
        """对每个 qty > 0 持仓创建 close 预订单 + 订单，绕过审批直接进入 CREATED。"""
        latest = await PositionSnapshot.filter(
            account_id=account_id,
            limit=1,
            order_by=PositionSnapshot.snapshot_date.desc(),
        )
        if not latest:
            logger.info("Kill Switch: 账户无持仓快照 account_id=%s", account_id)
            return []
        positions = await PositionSnapshot.filter(
            account_id=account_id,
            snapshot_date=latest[0].snapshot_date,
            limit=None,
        )
        active_positions = [p for p in positions if p.qty and p.qty > 0]
        if not active_positions:
            logger.info("Kill Switch: 账户无可平持仓 account_id=%s", account_id)
            return []
        # 校验账户至少有一个策略实例（紧急全平的订单仍需挂接到某个实例）
        instances = await StrategyInstance.filter(account_id=account_id, limit=1)
        if not instances:
            raise BusinessException(
                message=f"账户没有策略实例，无法生成紧急全平订单: {account_id}",
            )
        today = today_shanghai()
        now = now_shanghai()
        workflow_run_id = f"kill_switch:{today.isoformat()}:{account_id}"
        order_ids: list[int] = []
        for position in active_positions:
            # 跳过 instance_id 为 None 的持仓（防止负数持仓）：
            # order.instance_id 必须与持仓匹配，_load_latest_position 才能查到。
            # 若 fallback 到其他 instance_id，_update_position_after_fill 会用
            # previous_qty=0 计算，SELL 时产生 qty = 0 - filled_qty 负数持仓。
            # 无 instance_id 的持仓需人工核实后处理。
            if position.instance_id is None:
                logger.warning(
                    "Kill Switch 跳过 instance_id 为 None 的持仓（无法安全平仓）: "
                    "account_id=%s symbol=%s qty=%s",
                    account_id, position.symbol, position.qty,
                )
                continue
            position_instance_id = position.instance_id
            pre_order = await PreOrder.create(
                instance_id=position_instance_id,
                signal_date=today,
                execution_date=today,
                symbol=position.symbol,
                side=PreOrderSide.CLOSE,
                target_weight=0,
                # float 适配 PreOrder.current_weight 的 Float 类型（Decimal→float 转换）；
                # kill_switch 场景下 current_weight 仅作快照，不参与迭代计算，精度风险可忽略。
                current_weight=float(position.weight or 0),
                target_qty=position.qty,
                order_type=OrderType.MARKET,
                sizing_strategy="kill_switch",
                status=PreOrderStatus.APPROVED,
                risk_check_passed=True,
                risk_check_detail={"reason": "manual_kill_switch", "operator": operator},
                approval_status=ApprovalStatus.APPROVED,
                approved_by=operator,
                approved_at=now,
                approval_comment=reason,
                idempotency_key=f"kill_switch:{account_id}:{today.isoformat()}:{position.symbol}",
                node_id="kill_switch",
            )
            order = await Order.create(
                account_id=account_id,
                platform_order_id=uuid4(),
                instance_id=position_instance_id,
                pre_order_id=pre_order.id,
                symbol=position.symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                order_price=None,
                order_qty=position.qty,
                filled_price=None,
                filled_qty=0,
                status=OrderStatus.CREATED,
                broker_order_id=None,
                reject_reason=None,
                signal_date=today,
                execution_date=today,
                workflow_run_id=workflow_run_id,
            )
            await OrderEvent.create(
                order_id=order.id,
                event_type=OrderEventType.CREATED,
                event_data={
                    "pre_order_id": pre_order.id,
                    "workflow_run_id": workflow_run_id,
                },
                operator=operator,
            )
            await OrderEvent.create(
                order_id=order.id,
                event_type=OrderEventType.RISK_CHECKED,
                event_data={"risk_check_detail": {"reason": "kill_switch_bypass"}},
                operator=operator,
            )
            order_ids.append(order.id)
        return order_ids

    async def _cancel_submitted_orders(
        self,
        cancel_specs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """事务外：调用 QMT 撤单。撤单回报由 QmtCallbackHandler 异步修正最终状态。"""
        results: list[dict[str, Any]] = []
        for spec in cancel_specs:
            order_id = spec["order_id"]
            broker_order_id = spec["broker_order_id"]
            try:
                ret = await self.qmt_trader.cancel_order(int(broker_order_id))
                results.append({
                    "order_id": order_id,
                    "broker_order_id": broker_order_id,
                    "cancel_result": ret,
                    "status": "cancel_succeeded" if ret == 0 else "cancel_failed",
                })
            except Exception as exc:
                logger.error(
                    "Kill Switch 撤单失败 order_id=%s broker_order_id=%s",
                    order_id,
                    broker_order_id,
                    exc_info=True,
                )
                results.append({
                    "order_id": order_id,
                    "broker_order_id": broker_order_id,
                    "status": "cancel_failed",
                    "error": str(exc),
                })
        return results

    async def _submit_close_orders(
        self,
        account: TradingAccount,
        order_ids: list[int],
        operator: str,
    ) -> list[dict[str, Any]]:
        """事务外：提交 close 订单到模拟撮合或 QMT。"""
        results: list[dict[str, Any]] = []
        for order_id in order_ids:
            try:
                if account.account_type == AccountType.PAPER:
                    result = await self.matching_service.submit_simulated_order(
                        order_id, operator,
                    )
                elif account.broker_type == BrokerType.QMT:
                    result = await self.execution_service.submit_qmt_order(
                        order_id, operator,
                    )
                else:
                    raise BusinessException(
                        message=f"不支持的券商类型: {account.broker_type}",
                    )
                results.append({
                    "order_id": order_id,
                    "status": "submitted",
                    "result": result,
                })
            except Exception as exc:
                logger.error(
                    "Kill Switch 平仓订单提交失败 order_id=%s",
                    order_id,
                    exc_info=True,
                )
                # 失败订单必须标记 REJECTED，避免僵尸 CREATED 状态被后续 submit 路径反复尝试。
                # mark_order_rejected 是独立 @transactional，与 submit_simulated_order 的事务回滚独立。
                try:
                    await self.execution_service.mark_order_rejected(
                        order_id, str(exc), operator,
                    )
                except Exception:
                    logger.error(
                        "Kill Switch 平仓订单标记 REJECTED 失败 order_id=%s",
                        order_id,
                        exc_info=True,
                    )
                results.append({
                    "order_id": order_id,
                    "status": "submit_failed",
                    "error": str(exc),
                })
        return results
