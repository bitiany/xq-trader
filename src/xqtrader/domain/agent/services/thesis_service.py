"""投研论点卡服务 — CRUD + Qdrant 索引"""

from datetime import date
from typing import Any, cast

from framework.commons.logger import get_logger
from framework.dal.transaction.transactional import transactional
from xqtrader.domain.agent.models.thesis import ResearchThesis
from xqtrader.domain.watermark.models.trade_calendar import TradeCalendar

from .memory_service import MemoryService

logger = get_logger("AGENT.THESIS")


class ThesisService:
    """投研论点卡读写服务"""

    async def get_thesis(self, symbol: str) -> dict[str, Any] | None:
        """读取标的的最新有效论点卡

        Args:
            symbol: 股票代码

        Returns:
            论点卡字典，无记录或已过期则 None
        """
        results = await ResearchThesis.filter(
            limit=1,
            order_by=ResearchThesis.created_at.desc(),
            symbol=symbol,
            status="active",
        )
        if not results:
            return None
        thesis = cast(dict[str, Any], results[0].to_dict())
        ref = await TradeCalendar.get_latest_trade_date()
        valid_until = thesis.get("valid_until")
        if ref and valid_until and valid_until < ref:
            logger.info(
                "论点卡已过期: symbol=%s valid_until=%s ref=%s",
                symbol,
                valid_until,
                ref,
            )
            return {
                "status": "expired",
                "symbol": symbol,
                "valid_until": (
                    valid_until.isoformat()
                    if isinstance(valid_until, date)
                    else valid_until
                ),
                "reason": f"valid_until expired: {valid_until}",
            }
        thesis["status"] = "active"
        return thesis

    async def reconcile_expired(self, symbol: str) -> int:
        """将已过期的 active 论点卡标记为 stale（显式治理，非读路径副作用）。"""
        results = await ResearchThesis.filter(
            limit=1,
            order_by=ResearchThesis.created_at.desc(),
            symbol=symbol,
            status="active",
        )
        if not results:
            return 0
        thesis = cast(dict[str, Any], results[0].to_dict())
        ref = await TradeCalendar.get_latest_trade_date()
        valid_until = thesis.get("valid_until")
        if not ref or not valid_until or valid_until >= ref:
            return 0
        return int(await self.mark_stale(
            symbol,
            reason=f"valid_until expired: {valid_until}",
        ))

    async def reconcile_all_expired(self) -> int:
        """批量将已过期的 active 论点卡标记为 stale（Worker 定时治理）。"""
        ref = await TradeCalendar.get_latest_trade_date()
        if ref is None:
            return 0
        rows = await ResearchThesis.filter(
            status="active",
            valid_until__lt=ref,
        )
        symbols = sorted({row.symbol for row in rows})
        total = 0
        for symbol in symbols:
            total += await self.reconcile_expired(symbol)
        if total:
            logger.info(
                "论点卡批量过期治理完成: symbols=%d affected=%d ref=%s",
                len(symbols),
                total,
                ref,
            )
        return total

    @transactional(bind_key="default")
    async def save_thesis(
        self,
        symbol: str,
        as_of: date,
        valid_until: date,
        direction: str,
        info_gap: dict,
        logic_gap: dict,
        surprise_gap: dict,
        catalysts: dict,
        core_assumption: str,
        falsification: dict,
        tracking_metrics: dict,
        invalidation_rules: dict,
    ) -> dict[str, Any]:
        """保存论点卡（旧 active 记录标记 stale，新记录写入 + Qdrant 索引）"""
        await ResearchThesis.update_by(
            {"status": "stale"},
            symbol=symbol,
            status="active",
        )

        thesis = await ResearchThesis.create(
            symbol=symbol,
            as_of=as_of,
            valid_until=valid_until,
            direction=direction,
            info_gap=info_gap,
            logic_gap=logic_gap,
            surprise_gap=surprise_gap,
            catalysts=catalysts,
            core_assumption=core_assumption,
            falsification=falsification,
            tracking_metrics=tracking_metrics,
            invalidation_rules=invalidation_rules,
            status="active",
        )

        summary = f"{symbol} {direction} {core_assumption}"
        MemoryService.get_instance().index_memory(
            text=summary,
            payload={
                "symbol": symbol,
                "as_of": str(as_of),
                "direction": direction,
                "type": "thesis",
            },
        )

        logger.info("论点卡已保存: symbol=%s, direction=%s", symbol, direction)
        return cast(dict[str, Any], thesis.to_dict())

    @transactional(bind_key="default")
    async def mark_stale(self, symbol: str, reason: str = "") -> int:
        """标记标的的论点卡为 stale

        Returns:
            受影响行数
        """
        count = await ResearchThesis.update_by(
            {"status": "stale"},
            symbol=symbol,
            status="active",
        )
        logger.info("论点卡标记 stale: symbol=%s, reason=%s, affected=%d", symbol, reason, count)
        return count
