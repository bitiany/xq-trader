"""投研论点卡服务 — CRUD + Qdrant 索引"""

import logging
from datetime import date
from typing import Any, cast

from framework.dal.transaction.transactional import transactional
from xqtrader.domain.agent.models.thesis import ResearchThesis

from .memory_service import MemoryService

logger = logging.getLogger("AGENT.THESIS")


class ThesisService:
    """投研论点卡读写服务"""

    async def get_thesis(self, symbol: str) -> dict[str, Any] | None:
        """读取标的的最新有效论点卡

        Args:
            symbol: 股票代码

        Returns:
            论点卡字典，无则 None
        """
        results = await ResearchThesis.filter(
            limit=1,
            order_by=ResearchThesis.created_at.desc(),
            symbol=symbol,
            status="active",
        )
        if not results:
            return None
        return cast(dict[str, Any], results[0].to_dict())

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
        # 旧 active 记录标记 stale
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

        # Qdrant 向量索引
        summary = f"{symbol} {direction} {core_assumption}"
        try:
            MemoryService.get_instance().index_memory(
                text=summary,
                payload={
                    "symbol": symbol,
                    "as_of": str(as_of),
                    "direction": direction,
                    "type": "thesis",
                },
            )
        except Exception:
            logger.error("论点卡 Qdrant 索引失败: symbol=%s", symbol, exc_info=True)

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
