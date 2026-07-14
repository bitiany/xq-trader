"""事件扫描与论点卡失效触发任务（定时调度）。

架构文档 §11.3 第三层 + §20 阶段 5 任务 4。

执行流程：
  1. 加载需要扫描的标的列表（默认从 ResearchThesis.status=active 加载）
  2. 调用 EventDetector.detect_events() 两层检测
     - Layer 1 关键词扫描（毫秒级）
     - Layer 2 LLM 精细识别（秒级，可选）
  3. 按 symbol 分组，对每个 symbol 调用 EventThesisService.evaluate_impact()
     - 利空命中证伪条件 → mark_thesis_stale
     - 利好事件 → 建议更新 catalysts
     - 无影响 → 无操作
  4. 返回扫描摘要

调度：
  - 默认每个交易日 18:30 扫描一次（plugin.yaml 中 cron: "30 18 * * 1-5"）
  - 收盘后扫描，覆盖当日全部新闻/公告

防重入：
  - BaseTask 默认 prevent_concurrent=True，防止任务堆积
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from framework.commons.logger import get_logger
from framework.scheduler.base_task import BaseTask
from xqtrader.domain.agent.models.thesis import ResearchThesis
from xqtrader.domain.event.services.event_detector import EventDetector
from xqtrader.domain.event.services.event_thesis_service import EventThesisService

logger = get_logger("EVENT.SCAN")

# 默认回溯天数（仅扫描昨今两天的新事件）
_DEFAULT_DAYS = 1


class EventScanTask(BaseTask):
    """事件扫描与论点卡失效触发任务。

    入参：
      - days: 回溯天数（默认 1）
      - symbols: 显式标的列表（为空时自动加载 status=active 的论点卡标的）
      - skip_llm: 是否跳过 Layer 2 LLM 识别（默认 False）
    """

    task_name = "event.scan"
    description = "事件扫描与论点卡失效触发-定时扫描近期新闻/公告事件信号"
    time_limit = 1800
    max_retries = 2

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        days: int = int(kwargs.get("days", _DEFAULT_DAYS))
        symbols_input: list[str] | None = kwargs.get("symbols")
        skip_llm: bool = bool(kwargs.get("skip_llm", False))

        # 1. 加载扫描标的列表
        symbols = await self._load_scan_symbols(symbols_input)
        if not symbols:
            logger.info("[event.scan] 无待扫描标的（无 status=active 论点卡）")
            return {
                "scanned_symbols": 0,
                "detected_events": 0,
                "triggered_invalidations": 0,
                "catalyst_updates": 0,
            }

        logger.info(
            "[event.scan] 开始扫描: symbols=%d days=%d skip_llm=%s",
            len(symbols), days, skip_llm,
        )

        # 2. 事件检测
        detector = EventDetector()
        events = await detector.detect_events(
            symbols=symbols,
            event_types=None,
            days=days,
            skip_llm=skip_llm,
        )

        logger.info(
            "[event.scan] 事件检测完成: total=%d (skip_llm=%s)",
            len(events), skip_llm,
        )

        # 3. 按 symbol 分组评估影响
        events_by_symbol: dict[str, list[Any]] = defaultdict(list)
        for ev in events:
            if ev.symbol:
                events_by_symbol[ev.symbol].append(ev)

        thesis_service = EventThesisService()
        triggered_invalidations = 0
        catalyst_updates = 0
        impacted_symbols: list[str] = []

        for symbol, symbol_events in events_by_symbol.items():
            try:
                result = await thesis_service.evaluate_impact(
                    symbol=symbol, events=symbol_events,
                )
                if result.action == "mark_thesis_stale":
                    triggered_invalidations += 1
                    impacted_symbols.append(symbol)
                    logger.info(
                        "[event.scan] 论点卡已失效: symbol=%s reason=%s",
                        symbol, result.reason,
                    )
                elif result.action == "update_catalysts":
                    catalyst_updates += 1
                    logger.info(
                        "[event.scan] 催化剂更新建议: symbol=%s reason=%s",
                        symbol, result.reason,
                    )
            except Exception:
                logger.error(
                    "[event.scan] 评估事件影响失败: symbol=%s events=%d",
                    symbol, len(symbol_events),
                    exc_info=True,
                )

        logger.info(
            "[event.scan] 扫描完成: symbols=%d events=%d invalidations=%d catalysts=%d",
            len(symbols), len(events), triggered_invalidations, catalyst_updates,
        )

        return {
            "scanned_symbols": len(symbols),
            "detected_events": len(events),
            "triggered_invalidations": triggered_invalidations,
            "catalyst_updates": catalyst_updates,
            "impacted_symbols": impacted_symbols,
            "scan_date": date.today().isoformat(),
        }

    @staticmethod
    async def _load_scan_symbols(
        symbols_input: list[str] | None,
    ) -> list[str]:
        """加载扫描标的列表。

        - 显式传入：直接使用
        - 未传入：从 ResearchThesis 表加载全部 status=active 的 symbol
        """
        if symbols_input:
            return list(dict.fromkeys(symbols_input))  # 去重保序

        theses = await ResearchThesis.filter(
            status="active",
            limit=None,
        )
        symbols = sorted({t.symbol for t in theses if t.symbol})
        return symbols
