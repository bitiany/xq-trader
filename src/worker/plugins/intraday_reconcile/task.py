"""分钟级K线盘后回补任务。

数据源：QMT (xtdata)，回补 1 分钟 K 线行情写入 CandlestickMinute 表（sdc_candlestick_1m）。
适用场景：
  - 盘后全量补全（15:35 定时触发或手动触发）
  - 历史日期回补（指定 trade_date / end_date 范围）
  - 动态股票池自动加载（自选池 + 持仓 + 已审批 pre_order）

并发模型：ConcurrentRunner 生产者-消费者，N 个消费者并发拉取，单标的失败不影响其他。
幂等性：bulk_create_or_update + on_conflict(symbol, trade_time)，重复回补安全。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from framework.commons.concurrent import ConcurrentRunner
from framework.commons.logger import get_logger
from framework.scheduler.base_task import BaseTask
from xqtrader.broker.services.qmt_data_collector import QmtDataCollector
from xqtrader.domain.market.intraday.dynamic_pool import load_dynamic_stock_pool
from xqtrader.domain.market.intraday.intraday_monitor_task import dataframe_to_minute_models
from xqtrader.domain.market.models.candlestick import CandlestickMinute

logger = get_logger(__name__)


class IntradayReconcileTask(BaseTask):
    """盘后数据补全与对账任务。

    入参：
      - stock_codes: 股票代码列表（为空时自动加载动态股票池）
      - trade_date: 回补起始日期（YYYY-MM-DD，默认今天）
      - end_date: 回补结束日期（YYYY-MM-DD，为空时等于 trade_date，单日回补）
      - concurrency: 并发数（默认 5）
      - max_count: 最大标的数量（用于测试，0 表示不限）
    """

    task_name = "market.intraday_reconcile"
    description = "盘后数据补全与对账（QMT xtdata）"

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        stock_codes: list[str] | None = kwargs.get("stock_codes")
        trade_date_str: str | None = kwargs.get("trade_date")
        end_date_str: str | None = kwargs.get("end_date")
        concurrency: int = kwargs.get("concurrency", 5)
        max_count: int = kwargs.get("max_count", 0)

        # 解析日期
        if trade_date_str:
            start_dt = date.fromisoformat(trade_date_str)
        else:
            start_dt = date.today()
        end_dt = date.fromisoformat(end_date_str) if end_date_str else start_dt

        if end_dt < start_dt:
            return {"error": f"end_date({end_dt}) 不能早于 trade_date({start_dt})"}

        # 获取标的列表
        if not stock_codes:
            stock_codes = await load_dynamic_stock_pool()
            if not stock_codes:
                logger.warning("[minute.backfill] 动态股票池为空，无标的可回补")
                return {"total": 0, "succeeded": 0, "failed": 0, "rows_persisted": 0}

        if max_count > 0 and len(stock_codes) > max_count:
            stock_codes = stock_codes[:max_count]
            logger.info("[minute.backfill] 限制标的数量: max_count=%d", max_count)

        logger.info(
            "[minute.backfill] 开始回补: stocks=%d range=%s~%s concurrency=%d",
            len(stock_codes), start_dt, end_dt, concurrency,
        )

        # 初始化 QMT 数据采集器并连接
        collector = QmtDataCollector()
        try:
            await collector.connect()
            logger.info("[minute.backfill] QMT 行情连接成功")
        except Exception as e:
            logger.error("[minute.backfill] QMT 行情连接失败: %s", e, exc_info=True)
            return {"error": f"QMT 行情连接失败: {e}", "total": 0, "succeeded": 0, "failed": 0}

        # 生成日期列表（含起止）
        date_list = _generate_date_range(start_dt, end_dt)

        # 构建回补任务项：(symbol, trade_date) 笛卡尔积
        items: list[tuple[str, date]] = [
            (sym, d) for sym in stock_codes for d in date_list
        ]

        # 并发拉取并持久化
        runner = ConcurrentRunner[tuple[str, date], int](
            concurrency=concurrency,
            queue_maxsize=concurrency * 2,
            log_name="minute.backfill",
        )

        async def process_item(item: tuple[str, date]) -> int | None:
            sym, dt = item
            return await self._fetch_and_persist(collector, sym, dt)

        result = await runner.run_items(items, processor=process_item)

        total_rows = sum(r for r in result.succeeded if r is not None)

        logger.info(
            "[minute.backfill] 回补完成: stocks=%d dates=%d items=%d "
            "succeeded=%d failed=%d rows=%d duration_ms=%d",
            len(stock_codes), len(date_list), result.total,
            result.success_count, result.failure_count, total_rows, result.duration_ms,
        )

        return {
            "total": result.total,
            "succeeded": result.success_count,
            "failed": result.failure_count,
            "rows_persisted": total_rows,
            "duration_ms": result.duration_ms,
            "errors": result.to_dict().get("errors", [])[:10],  # 最多返回10条错误
        }

    async def _fetch_and_persist(
        self,
        collector: QmtDataCollector,
        symbol: str,
        trade_date: date,
    ) -> int:
        """拉取单标的单日分钟数据并持久化。

        Returns:
            写入的记录数
        """
        start_time = trade_date.strftime("%Y%m%d")
        # end_time 含当日 15:00，确保拿到完整交易日
        end_time = f"{trade_date.strftime('%Y%m%d')}150000"

        try:
            result = await collector.fetch_kline_minute(
                stock_list=[symbol],
                period="1m",
                start_time=start_time,
                end_time=end_time,
            )
        except Exception as e:
            logger.error(
                "[minute.backfill] 拉取失败: symbol=%s date=%s error=%s",
                symbol, trade_date, e, exc_info=True,
            )
            raise

        df = result.get(symbol)
        if df is None or df.empty:
            logger.debug("[minute.backfill] 无数据: symbol=%s date=%s", symbol, trade_date)
            return 0

        # 转换为 CandlestickMinute 实例
        instances = dataframe_to_minute_models(df, symbol)
        if not instances:
            return 0

        # 幂等写入
        count = await CandlestickMinute.bulk_create_or_update(
            instances,
            on_conflict=["symbol", "trade_time"],
            update_fields=["open", "high", "low", "close", "volume", "amount",
                           "trade_date", "data_source"],
            batch_size=500,
        )

        logger.debug(
            "[minute.backfill] 持久化完成: symbol=%s date=%s rows=%d",
            symbol, trade_date, count,
        )
        return count


def _generate_date_range(start: date, end: date) -> list[date]:
    """生成日期列表（含起止，仅工作日）。"""
    dates: list[date] = []
    current = start
    while current <= end:
        # 跳过周末（0=周一...6=周日）
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    return dates
