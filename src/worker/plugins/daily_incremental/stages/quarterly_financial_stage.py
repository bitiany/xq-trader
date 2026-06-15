"""季度财务数据增量采集 Stage — 增量采集财务指标/利润表/资产负债表。

执行流程：
  1. 检查水位表中三个季度数据源（financial_indicator / income_statement / balance_sheet）的水位
  2. 若当前日期 > 最新水位日期，则触发增量采集
  3. 三个数据源共享同一个采集逻辑：按标的逐个采集，水位基于 ann_date

数据源：Tushare fina_indicator / income / balancesheet 接口。
增量采集与日频数据不同，季度数据只在财报季有更新（1/4/7/10 月公告密集期）。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from framework.commons.logger import get_logger
from framework.pipeline import Pipeline, PipelineEngine
from worker.plugins.aspects import WatermarkAspect
from worker.plugins.balance_sheet.task import (
    CleanStage as BalanceSheetCleanStage,
)
from worker.plugins.balance_sheet.task import (
    DownloadStage as BalanceSheetDownloadStage,
)
from worker.plugins.balance_sheet.task import (
    PersistStage as BalanceSheetPersistStage,
)
from worker.plugins.financial_indicator.task import (
    CleanStage as FinaIndicatorCleanStage,
)
from worker.plugins.financial_indicator.task import (
    DownloadStage as FinaIndicatorDownloadStage,
)
from worker.plugins.financial_indicator.task import (
    PersistStage as FinaIndicatorPersistStage,
)
from worker.plugins.income_statement.task import (
    CleanStage as IncomeCleanStage,
)
from worker.plugins.income_statement.task import (
    DownloadStage as IncomeDownloadStage,
)
from worker.plugins.income_statement.task import (
    PersistStage as IncomePersistStage,
)
from xqtrader.domain.security.models import Security
from xqtrader.domain.watermark.models.collect_watermark import CollectWatermark

logger = get_logger(__name__)

# 三个季度数据源共享的 DATA_TYPE 前缀
_QUARTERLY_DATA_TYPES = ["financial_indicator", "income_statement", "balance_sheet"]


class QuarterlyFinancialIncrementalStage:
    """季度财务数据增量采集 Stage。

    判断逻辑：检查三个季度数据源的水位，若当前日期 > 最新水位，则触发增量采集。
    三个数据源（fina_indicator / income / balance_sheet）按顺序串行执行，
    每个数据源内部按标的并发采集。
    """

    DATA_TYPE = "quarterly_financial"

    async def execute(self, start_date: date, end_date: date) -> dict[str, Any]:
        """执行季度财务数据增量采集。

        Args:
            start_date: 增量起始日期（水位日期 + 1）
            end_date: 增量结束日期（当前日期）
        """
        results: dict[str, Any] = {}

        # 获取全市场标的
        stock_codes = await self._get_all_stock_codes()
        if not stock_codes:
            logger.warning("[quarterly.incremental] 未找到任何标的代码")
            return {"status": "SKIPPED", "reason": "no_stocks"}

        start_date_str = start_date.strftime("%Y-%m-%d")

        # 依次执行三个数据源的增量采集
        for data_type, dl_cls, clean_cls, persist_cls in [
            ("financial_indicator", FinaIndicatorDownloadStage, FinaIndicatorCleanStage, FinaIndicatorPersistStage),
            ("income_statement", IncomeDownloadStage, IncomeCleanStage, IncomePersistStage),
            ("balance_sheet", BalanceSheetDownloadStage, BalanceSheetCleanStage, BalanceSheetPersistStage),
        ]:
            # 检查该数据源是否有水位
            has_watermark = await self._has_watermark(data_type)
            if not has_watermark:
                logger.info("[quarterly.incremental] %s: 无水位记录，跳过（需先全量采集）", data_type)
                results[data_type] = {"status": "SKIPPED", "reason": "no_watermark"}
                continue

            logger.info(
                "[quarterly.incremental] %s: 增量采集 start=%s stocks=%d",
                data_type, start_date_str, len(stock_codes),
            )

            pipeline = Pipeline(
                name=data_type,
                stages=[dl_cls(), clean_cls(), persist_cls()],
                aspects=[WatermarkAspect(data_type=data_type)],
            )

            global_ctx: dict[str, Any] = {"collect_date": start_date_str}
            engine = PipelineEngine(
                pipelines=[pipeline],
                concurrency=3,
                global_context=global_ctx,
            )
            result = await engine.execute(stock_codes)
            results[data_type] = result.to_dict()

        logger.info("[quarterly.incremental] 全部完成: %s", results)
        return results

    @staticmethod
    async def _get_all_stock_codes() -> list[str]:
        """获取全市场 A 股标的代码。"""
        rows = await Security.filter(
            list_status="L",
            order_by=Security.symbol.asc(),
        )
        return [row.symbol for row in rows]

    @staticmethod
    async def _has_watermark(data_type: str) -> bool:
        """检查指定数据源是否有水位记录。"""
        rows = await CollectWatermark.filter(data_type=data_type, status="active")
        return len(rows) > 0
