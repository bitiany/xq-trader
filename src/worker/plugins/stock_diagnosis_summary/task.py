"""诊股 AI 解读异步生成 — 基于最新快照更新 summary 字段。"""

from __future__ import annotations

from typing import Any

from framework.commons.logger import get_logger
from framework.scheduler.base_task import BaseTask
from xqtrader.domain.security.services.stock_diagnosis_service import StockDiagnosisService

logger = get_logger(__name__)


class StockDiagnosisSummaryTask(BaseTask):
    """为单标的重新生成 LLM 诊股解读并写回快照。"""

    task_name = "market.stock_diagnosis_summary"

    async def _run_impl(self, upstream: Any = None, symbol: str = "", **kwargs: Any) -> dict[str, Any]:
        _ = upstream
        _ = kwargs
        if not symbol:
            raise ValueError("symbol 不能为空")

        service = StockDiagnosisService()
        result = await service.regenerate_ai_summary(symbol)
        logger.info("诊股 AI 解读完成: %s as_of=%s", symbol, result.get("as_of"))
        return result
