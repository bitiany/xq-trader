"""动态股票池加载器 - 获取全部账户去重自选池 + 持仓 + 已审批 pre_order

设计要点：
- 全部账户去重：模拟盘 account_type=paper 与实盘 account_type=live 的自选池独立存储，
  需跨账户查询并去重
- 持仓：从 td_position_snapshot 查最新持仓
- 已审批 pre_order：从 td_pre_order 查 pending_approval/approved 状态的标的
"""

from __future__ import annotations

import logging
from datetime import date

from xqtrader.domain.trading.models.order import PreOrder
from xqtrader.domain.trading.models.position import PositionSnapshot
from xqtrader.domain.trading.models.watchlist import Watchlist, WatchlistItem

logger = logging.getLogger("INTRADAY.POOL")


async def load_dynamic_stock_pool(reference_date: date | None = None) -> list[str]:
    """加载动态股票池（全部账户去重自选池 + 持仓 + 已审批 pre_order）

    Args:
        reference_date: 参考日期（持仓快照查询用），None 表示最新

    Returns:
        去重后的证券代码列表
    """
    # 1. 全部账户去重自选池
    watchlists = await Watchlist.filter(limit=None)
    watchlist_ids = [w.id for w in watchlists] if watchlists else []
    items = await WatchlistItem.filter(
        watchlist_id__in=watchlist_ids,
        is_enabled=1,
        limit=None,
    ) if watchlist_ids else []
    watchlist_symbols = {item.symbol for item in items if item.symbol and item.symbol.strip()} if items else set()

    # 2. 持仓标的（按最新快照日期过滤，避免历史已清仓标的被错误纳入）
    if reference_date is None:
        # 未指定日期时，先查最新快照日期
        latest = await PositionSnapshot.get_one_or_none(
            order_by=PositionSnapshot.snapshot_date.desc(),
        )
        if latest is None:
            positions = []
        else:
            reference_date = latest.snapshot_date
            positions = await PositionSnapshot.filter(
                snapshot_date=reference_date,
                limit=None,
            )
    else:
        positions = await PositionSnapshot.filter(
            snapshot_date=reference_date,
            limit=None,
        )
    position_symbols = (
        {p.symbol for p in positions if p.qty > 0 and p.symbol and p.symbol.strip()}
        if positions else set()
    )

    # 3. 已审批 pre_order 标的（pending_approval 或 approved）
    pre_orders = await PreOrder.filter(
        status__in=["pending_approval", "approved"],
        limit=None,
    )
    pre_order_symbols = {po.symbol for po in pre_orders if po.symbol and po.symbol.strip()} if pre_orders else set()

    # 合并去重
    dynamic_pool = sorted(watchlist_symbols | position_symbols | pre_order_symbols)

    logger.info(
        "动态股票池加载完成: total=%d, watchlist=%d, positions=%d, pre_orders=%d",
        len(dynamic_pool), len(watchlist_symbols),
        len(position_symbols), len(pre_order_symbols),
    )
    return dynamic_pool
