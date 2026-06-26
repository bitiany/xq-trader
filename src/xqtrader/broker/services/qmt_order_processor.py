"""QMT 回调 → OMS 事件链路处理器。

将 QMT 的委托/成交/资金/持仓回调转换为 OMS 内部状态变更：
- on_stock_order → 更新 Order.status + 追加 OrderEvent
- on_stock_trade → 创建 Trade + 累计 Order.filled_qty/filled_price + 追加 OrderEvent
- on_stock_asset → 更新 TradingAccount 可用/冻结资金
- on_stock_position → 刷新 PositionSnapshot 市值

注意：QMT 回调在 QMT 内部线程触发，本类的 async 方法由
QmtCallbackHandler 通过 asyncio.run_coroutine_threadsafe 调度到主事件循环执行。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from framework.commons.logger import get_logger
from framework.commons.time_util import now_shanghai
from framework.dal.transaction.transactional import transactional
from xqtrader.domain.trading.enums import (
    OrderEventType,
    OrderStatus,
)
from xqtrader.domain.trading.models.account import TradingAccount
from xqtrader.domain.trading.models.order import Order, OrderEvent, Trade
from xqtrader.domain.trading.models.position import PositionSnapshot

logger = get_logger(__name__)


class QmtOrderStatus:
    """QMT 委托状态常量（来自 xtconstant）。"""

    UNREPORTED = 48        # 未报
    WAIT_REPORTING = 49    # 待报
    REPORTED = 50          # 已报
    REPORTED_CANCEL = 51   # 已报撤单
    PARTSUCC_CANCEL = 52   # 部成撤
    PART_CANCEL = 53       # 部撤
    CANCELED = 54          # 已撤
    PART_SUCC = 55         # 部成
    SUCCEEDED = 56         # 已成
    JUNK = 57              # 废单
    UNKNOWN = 255          # 未知


def _map_qmt_order_status(qmt_status: int) -> str | None:
    """将 QMT 委托状态映射为 OMS OrderStatus；不可识别返回 None。"""
    mapping = {
        QmtOrderStatus.UNREPORTED: OrderStatus.CREATED,
        QmtOrderStatus.WAIT_REPORTING: OrderStatus.CREATED,
        QmtOrderStatus.REPORTED: OrderStatus.SUBMITTED,
        QmtOrderStatus.REPORTED_CANCEL: OrderStatus.CANCELLED,
        QmtOrderStatus.PARTSUCC_CANCEL: OrderStatus.CANCELLED,
        QmtOrderStatus.PART_CANCEL: OrderStatus.CANCELLED,
        QmtOrderStatus.CANCELED: OrderStatus.CANCELLED,
        QmtOrderStatus.PART_SUCC: OrderStatus.PARTIAL_FILLED,
        QmtOrderStatus.SUCCEEDED: OrderStatus.FILLED,
        QmtOrderStatus.JUNK: OrderStatus.REJECTED,
    }
    return mapping.get(qmt_status)


class QmtOrderProcessor:
    """QMT 回调 → OMS 事件处理器。

    所有方法均为 async，由 QmtCallbackHandler 通过主事件循环调度。
    单个回调失败不应阻塞其他回调，故内部捕获异常并记录日志。
    """

    @transactional(bind_key="trading")
    async def process_order_callback(self, order_data: dict[str, Any]) -> None:
        """处理 QMT on_stock_order 回调。

        更新 Order.status（按 QMT 委托状态映射），追加 OrderEvent。
        若 broker_order_id 尚未写回（提交→已报间的竞态），跳过等待下次回调。
        """
        broker_order_id = str(order_data.get("order_id") or "").strip()
        if not broker_order_id:
            logger.warning("QMT 委托回调缺少 order_id，跳过: %s", order_data)
            return

        order = await self._find_order_by_broker_id(broker_order_id)
        if order is None:
            # 僵尸订单场景：broker 端已下单但本地 broker_order_id 未写回
            # （submit_qmt_order 中 broker 调用成功但 mark_qmt_order_submitted 失败时发生）。
            # 静默 return 会导致成交回报永久丢失，此处必须 critical 告警 + 保留原始负载，
            # 由对账任务/人工核实后修复（如通过 broker_order_id 反查补单）。
            logger.error(
                "QMT 委托回调未匹配到订单（疑似僵尸订单），需人工对账: "
                "broker_order_id=%s order_data=%s",
                broker_order_id, order_data,
            )
            return

        qmt_status = int(order_data.get("order_status") or QmtOrderStatus.UNKNOWN)
        new_status = _map_qmt_order_status(qmt_status)
        if new_status is None:
            logger.warning("QMT 委托回调状态不可识别: order_id=%s qmt_status=%s", order.id, qmt_status)
            return

        # 解耦状态变更与成交量同步：QMT 多次推送 PARTIAL_FILLED 时状态未变但 traded_volume 递增，
        # 必须同步 OMS 端成交量，避免与 broker 端长期不一致。
        update_data: dict[str, Any] = {}
        if new_status != order.status:
            update_data["status"] = new_status
            if new_status == OrderStatus.REJECTED:
                update_data["reject_reason"] = str(order_data.get("status_msg") or "QMT 废单")[:256]
        # 同步 QMT 端累计成交量（以 QMT 回报为准）
        traded_volume = int(order_data.get("traded_volume") or 0)
        if traded_volume > 0 and traded_volume != order.filled_qty:
            update_data["filled_qty"] = traded_volume
            traded_price = order_data.get("traded_price")
            if traded_price:
                update_data["filled_price"] = Decimal(str(traded_price))

        # 状态与成交量均无变化，跳过空 UPDATE
        if not update_data:
            return

        await order.update(update_data)
        # 仅状态变更才追加 OrderEvent，避免成交量同步重复记录事件
        if "status" in update_data:
            await OrderEvent.create(
                order_id=order.id,
                event_type=self._event_type_for_status(new_status),
                event_data={
                    "broker_order_id": broker_order_id,
                    "qmt_status": qmt_status,
                    "status_msg": order_data.get("status_msg"),
                    "traded_volume": traded_volume,
                },
                operator="qmt_callback",
            )
        logger.info(
            "QMT 委托回调已处理: order_id=%s broker_order_id=%s status=%s->%s update_fields=%s",
            order.id, broker_order_id, order.status,
            update_data.get("status", order.status),
            list(update_data.keys()),
        )

    @transactional(bind_key="trading")
    async def process_trade_callback(self, trade_data: dict[str, Any]) -> None:
        """处理 QMT on_stock_trade 回调。

        幂等创建 Trade 记录（按 broker_trade_id 去重），并累计 Order.filled_qty/price。
        """
        broker_order_id = str(trade_data.get("order_id") or "").strip()
        broker_trade_id = str(trade_data.get("traded_id") or "").strip()
        stock_code = str(trade_data.get("stock_code") or "").strip()
        if not broker_order_id or not stock_code:
            logger.warning("QMT 成交回报缺少关键字段，跳过: %s", trade_data)
            return

        # broker_trade_id 为成交回报唯一键，缺失时无法做幂等去重，
        # QMT 断线重连会重发同一笔回调，缺失时直接入库会重复累计 filled_qty。
        # 此处拒绝处理并记录原始负载，由人工/对账核实。
        if not broker_trade_id:
            logger.error(
                "QMT 成交回报缺少 traded_id，无法幂等去重，拒绝处理: %s",
                trade_data,
            )
            return

        # 幂等：同一 broker_trade_id 不重复入库
        existing = await Trade.get_one_or_none(broker_trade_id=broker_trade_id)
        if existing is not None:
            logger.info("QMT 成交回报已处理，跳过: broker_trade_id=%s", broker_trade_id)
            return

        # 成交回报查询含 FILLED 终态：委托回调可能先于成交回调被处理（QMT 重连重放/
        # 调度乱序），导致订单已进入 FILLED；若仅查未终态会丢失新的成交回报。
        # 幂等已由 broker_trade_id 保证，此处查询放宽至 FILLED 避免数据丢失。
        order = await self._find_order_for_trade(broker_order_id)
        if order is None:
            # 僵尸订单场景：与 process_order_callback 同源，成交回报永久丢失风险更高。
            logger.error(
                "QMT 成交回报未匹配到订单（疑似僵尸订单），需人工对账: "
                "broker_order_id=%s stock=%s trade_data=%s",
                broker_order_id, stock_code, trade_data,
            )
            return

        filled_price = Decimal(str(trade_data.get("traded_price") or 0))
        filled_qty = int(trade_data.get("traded_volume") or 0)
        if filled_qty <= 0 or filled_price <= 0:
            logger.warning("QMT 成交回报数量/价格非法，跳过: %s", trade_data)
            return
        filled_amount = Decimal(str(trade_data.get("traded_amount") or 0)) or (filled_price * Decimal(filled_qty))

        # 账户：从 Order.account_id 取
        account_id = order.account_id
        # 实例 ID 与买卖方向以 Order 为准（避免 QMT 编码差异）
        side = order.side

        trade = await Trade.create(
            order_id=order.id,
            account_id=account_id,
            symbol=stock_code,
            side=side,
            filled_price=filled_price,
            filled_qty=filled_qty,
            filled_amount=filled_amount,
            trade_time=now_shanghai(),
            broker_trade_id=broker_trade_id,
        )

        # 累计订单成交数量与均价（QMT 可能多次部分成交）
        prev_filled_qty = int(order.filled_qty or 0)
        prev_filled_amount = (
            Decimal(str(order.filled_price or 0)) * Decimal(prev_filled_qty)
            if prev_filled_qty > 0
            else Decimal("0")
        )
        total_qty = prev_filled_qty + filled_qty
        total_amount = prev_filled_amount + filled_amount
        avg_price = (total_amount / Decimal(total_qty)) if total_qty > 0 else None
        new_status = (
            OrderStatus.FILLED
            if total_qty >= int(order.order_qty or 0)
            else OrderStatus.PARTIAL_FILLED
        )
        await order.update({
            "filled_qty": total_qty,
            "filled_price": avg_price,
            "status": new_status,
        })
        event_type = (
            OrderEventType.PARTIAL_FILLED
            if new_status == OrderStatus.PARTIAL_FILLED
            else OrderEventType.FILLED
        )
        await OrderEvent.create(
            order_id=order.id,
            event_type=event_type,
            event_data={
                "broker_trade_id": trade.broker_trade_id,
                "filled_price": str(filled_price),
                "filled_qty": filled_qty,
                "filled_amount": str(filled_amount),
                "cumulative_qty": total_qty,
            },
            operator="qmt_callback",
        )
        logger.info(
            "QMT 成交回报已处理: order_id=%s broker_trade_id=%s filled_qty=%s cumulative=%s status=%s",
            order.id, trade.broker_trade_id, filled_qty, total_qty, new_status,
        )

    @transactional(bind_key="trading")
    async def process_asset_callback(self, asset_data: dict[str, Any]) -> None:
        """处理 QMT on_stock_asset 回调。

        按 QMT 账户 ID 匹配 TradingAccount.account_code，刷新可用/冻结资金。
        """
        broker_account_id = str(asset_data.get("account_id") or "").strip()
        if not broker_account_id:
            logger.warning("QMT 资金回调缺少 account_id，跳过: %s", asset_data)
            return
        account = await TradingAccount.get_one_or_none(account_code=broker_account_id)
        if account is None:
            logger.info("QMT 资金回调未匹配到交易账户: account_code=%s", broker_account_id)
            return
        await account.update({
            "available_cash": Decimal(str(asset_data.get("cash") or 0)),
            "frozen_cash": Decimal(str(asset_data.get("frozen_cash") or 0)),
        })
        logger.info(
            "QMT 资金回调已处理: account_id=%s cash=%s frozen=%s",
            account.id, account.available_cash, account.frozen_cash,
        )

    @transactional(bind_key="trading")
    async def process_position_callback(self, position_data: dict[str, Any]) -> None:
        """处理 QMT on_stock_position 回调。

        更新 PositionSnapshot 的市值与可用数量（不重算 cost_price，由 fill 流程维护）。
        若无对应持仓快照，仅记录日志（避免与 fill 流程竞态）。
        """
        broker_account_id = str(position_data.get("account_id") or "").strip()
        stock_code = str(position_data.get("stock_code") or "").strip()
        if not broker_account_id or not stock_code:
            logger.warning("QMT 持仓回调缺少关键字段，跳过: %s", position_data)
            return
        account = await TradingAccount.get_one_or_none(account_code=broker_account_id)
        if account is None:
            logger.info("QMT 持仓回调未匹配到交易账户: account_code=%s", broker_account_id)
            return
        # 找到该账户下该标的的最新持仓快照（任意 instance）
        positions = await PositionSnapshot.filter(
            account_id=account.id,
            symbol=stock_code,
            limit=1,
            order_by=PositionSnapshot.snapshot_date.desc(),
        )
        if not positions:
            logger.info("QMT 持仓回调未匹配到持仓快照: account_id=%s symbol=%s", account.id, stock_code)
            return
        position = positions[0]
        volume = int(position_data.get("volume") or 0)
        can_use = int(position_data.get("can_use_volume") or 0)
        market_value = Decimal(str(position_data.get("market_value") or 0))
        await position.update({
            "qty": volume,
            "available_qty": can_use,
            "market_value": market_value,
        })
        logger.info(
            "QMT 持仓回调已处理: account_id=%s symbol=%s qty=%s available=%s",
            account.id, stock_code, volume, can_use,
        )

    @staticmethod
    def _event_type_for_status(status: str) -> str:
        mapping = {
            OrderStatus.SUBMITTED: OrderEventType.SUBMITTED,
            OrderStatus.PARTIAL_FILLED: OrderEventType.PARTIAL_FILLED,
            OrderStatus.FILLED: OrderEventType.FILLED,
            OrderStatus.CANCELLED: OrderEventType.CANCELLED,
            OrderStatus.REJECTED: OrderEventType.REJECTED,
        }
        return mapping.get(status, OrderEventType.SUBMITTED)

    @staticmethod
    async def _find_order_by_broker_id(broker_order_id: str) -> Order | None:
        """按 broker_order_id 查询订单（仅查未终态订单，避免重复处理）。"""
        orders = await Order.filter(
            broker_order_id=broker_order_id,
            status__in=[
                OrderStatus.CREATED,
                OrderStatus.RISK_CHECKED,
                OrderStatus.SUBMITTED,
                OrderStatus.PARTIAL_FILLED,
            ],
            limit=1,
        )
        return orders[0] if orders else None

    @staticmethod
    async def _find_order_for_trade(broker_order_id: str) -> Order | None:
        """按 broker_order_id 查询订单（含 FILLED 终态，专供成交回报使用）。

        委托回调可能先于成交回调被处理（QMT 重连重放/调度乱序），订单已进入 FILLED；
        若仅查未终态会丢失新的成交回报。幂等由 broker_trade_id 保证。
        """
        orders = await Order.filter(
            broker_order_id=broker_order_id,
            status__in=[
                OrderStatus.CREATED,
                OrderStatus.RISK_CHECKED,
                OrderStatus.SUBMITTED,
                OrderStatus.PARTIAL_FILLED,
                OrderStatus.FILLED,
            ],
            limit=1,
        )
        return orders[0] if orders else None
