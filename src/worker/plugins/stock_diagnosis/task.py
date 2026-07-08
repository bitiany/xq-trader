"""诊股评分快照批量计算 — 自选 + 持仓标的日频预计算。"""

from __future__ import annotations

from datetime import date
from typing import Any

from framework.commons.logger import get_logger
from framework.scheduler.base_task import BaseTask
from xqtrader.domain.security.services.stock_diagnosis_service import StockDiagnosisService
from xqtrader.domain.trading.models.position import PositionSnapshot
from xqtrader.domain.trading.models.watchlist import WatchlistItem

logger = get_logger(__name__)


async def resolve_diagnosis_symbols() -> list[str]:
    """合并启用自选股与最新持仓快照标的。"""
    symbols: set[str] = set()
    watchlist_items = await WatchlistItem.filter(is_enabled=1, limit=0)
    for item in watchlist_items:
        symbols.add(item.symbol)

    latest_rows = await PositionSnapshot.filter(
        order_by=PositionSnapshot.snapshot_date.desc(),
        limit=1,
    )
    if latest_rows:
        snapshot_date: date = latest_rows[0].snapshot_date
        positions = await PositionSnapshot.filter(snapshot_date=snapshot_date, qty__gt=0, limit=0)
        for pos in positions:
            symbols.add(pos.symbol)

    return sorted(symbols)


class StockDiagnosisSnapshotTask(BaseTask):
    """批量计算诊股评分并写入快照表。"""

    task_name = "market.stock_diagnosis_snapshot"

    async def run(
        self,
        upstream: Any = None,
        stock_codes: list[str] | None = None,
        max_count: int = 0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        _ = upstream
        _ = kwargs
        symbols = stock_codes or await resolve_diagnosis_symbols()
        if max_count > 0:
            symbols = symbols[:max_count]

        if not symbols:
            return {"processed": 0, "failed": 0, "symbols": [], "message": "无目标标的"}

        service = StockDiagnosisService()
        succeeded: list[str] = []
        failed: list[str] = []
        for symbol in symbols:
            try:
                await service.get_diagnosis(symbol, refresh=True, ai_summary=True)
                succeeded.append(symbol)
            except Exception:
                logger.exception("诊股快照计算失败: %s", symbol)
                failed.append(symbol)

        return {
            "processed": len(succeeded),
            "failed": len(failed),
            "symbols": succeeded,
            "failed_symbols": failed,
        }
