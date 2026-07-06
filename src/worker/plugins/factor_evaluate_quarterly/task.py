"""季频因子评估任务 — 按样本池评估季频财务因子的 IC/ICIR/分层回测/等级。

与日频评估（factor.evaluate_weekly）的区别：
  - 评估对象：update_freq=quarterly 的财务因子（B2-B5，约 32 个）
  - 评估窗口：季度数（8Q/12Q/16Q/20Q），换算为交易日（504/756/1008/1260）
  - IC horizon：1Q/2Q/4Q（63/126/252 交易日），非 1d/5d/10d/20d
  - 持久化：fac_financial_factor_stats（独立表），非 fac_factor_stats
  - 完全独立于日频评估，避免 PIT 前向填充导致的评估结果失真

评估流程（生产者-消费者并发模式）：
  1. 从 fac_factor_registry 读取 update_freq=quarterly 的活跃因子
  2. 逐样本池：预加载共享只读数据 → ConcurrentRunner 并发评估各因子 → 即时持久化
  3. 各因子独立加载 PIT 面板（load_financial_pit_panel + 截面预处理）
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from framework.commons.concurrent import ConcurrentRunner
from framework.commons.logger import get_logger
from framework.scheduler.base_task import BaseTask
from worker.plugins.utils import parse_list_param
from xqtrader.domain.factor.models.factor_pool import FacFactorPool
from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry
from xqtrader.domain.factor.models.financial_factor_stats import FacFinancialFactorStats
from xqtrader.domain.factor.services.cross_section_reader import CrossSectionReader
from xqtrader.domain.factor.services.grade_evaluator import GradeEvaluator
from xqtrader.domain.factor.services.ic_calculator import ICCalculator
from xqtrader.domain.factor.services.layered_backtest import LayeredBacktester
from xqtrader.domain.factor.services.pool_init import PoolInitService
from xqtrader.domain.watermark.models.trade_calendar import TradeCalendar

logger = get_logger("factor.evaluate_quarterly")

_RETENTION_YEARS = 7  # 季频评估需要更长历史（7年 ≈ 28季度，覆盖 20Q 窗口）

# 季频评估窗口：季度数 → 交易日数（1Q ≈ 63 交易日）
# - 8Q（2年）: 短周期窗口，捕捉财务因子的短期有效性
# - 12Q（3年）: 中周期窗口
# - 16Q（4年）: 中长周期窗口
# - 20Q（5年）: 长周期窗口，财务因子的基准窗口
_QUARTERLY_WINDOWS: dict[int, int] = {
    8: 504,   # 8Q ≈ 2年
    12: 756,  # 12Q ≈ 3年
    16: 1008, # 16Q ≈ 4年
    20: 1260, # 20Q ≈ 5年
}

# 季频 IC horizon：1Q/2Q/4Q（63/126/252 交易日）
_Q_HORIZONS: tuple[int, ...] = (63, 126, 252)
# 分层回测使用的 horizon 列名（1Q=63d，与 IC 主序列一致）
_Q_BACKTEST_RETURNS_COLUMN = "fwd_ret_63d"
# 季频年化因子：每年 4 个 1Q 周期（252/63=4）
_Q_ANNUALIZATION_FACTOR = 4

# 季频评估消费者数量
# 财务因子 PIT 加载是 DB I/O 密集型（每个因子 110s），4 并发是 DB I/O 安全水位
_QUARTERLY_EVAL_CONCURRENCY = 4

# 因子数据门禁阈值
_MIN_FACTOR_ROWS = 200  # 季频因子数据稀疏，阈值放宽（至少 200 个截面点）
_MIN_COVERAGE = 0.50    # 季频因子覆盖率较低，阈值放宽至 50%


@dataclass(frozen=True)
class _QuarterlyEvalContext:
    """季频单因子评估的共享只读上下文（所有消费者共用，不可变）。"""

    pool_id: str
    symbols: list[str]
    industry_map: dict[str, Any]
    market_cap_panel: Any
    membership: Any
    returns_panel: Any
    direction_map: dict[str, str]
    data_start_map: dict[str, date | None]
    reader: CrossSectionReader
    ic_calc: ICCalculator
    backtester: LayeredBacktester
    grade_eval: GradeEvaluator
    start_date: date
    end_date: date
    today: date
    pool_start_time: float


class FactorEvaluateQuarterlyTask(BaseTask):
    """季频因子评估任务。"""

    task_name = "factor.evaluate_quarterly"
    description = "按样本池评估季频财务因子的IC/ICIR/分层回测/等级"
    prevent_concurrent = True

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        task_start_time = time.monotonic()
        pool_ids = parse_list_param(kwargs.get("pool_ids"))
        factor_ids = parse_list_param(kwargs.get("factor_ids"))
        start_date = str(kwargs.get("start_date", ""))
        end_date = str(kwargs.get("end_date", ""))

        logger.info(
            "[factor.evaluate_quarterly] === 任务启动 === params: pool_ids=%s factor_ids=%s",
            pool_ids, factor_ids,
        )

        # 同步默认样本池配置
        t0 = time.monotonic()
        await PoolInitService().sync_default_pools()
        logger.info(
            "[factor.evaluate_quarterly] 样本池同步完成 耗时=%.2fs",
            time.monotonic() - t0,
        )

        # 从 DB 加载样本池配置
        if pool_ids:
            pools = await FacFactorPool.filter(pool_id__in=pool_ids, status="active")
        else:
            pools = await FacFactorPool.filter(status="active")
        if not pools:
            return {"status": "FAILED", "message": "No active pools found"}

        # 解析季频活跃因子列表（update_freq=quarterly）
        if factor_ids:
            all_factors = await FacFactorRegistry.filter(
                factor_id__in=factor_ids, status="active",
            )
        else:
            all_factors = await FacFactorRegistry.filter(status="active")
        # 只评估 update_freq=quarterly 的因子
        factors = [f for f in all_factors if (f.update_freq or "daily") == "quarterly"]
        if not factors:
            return {"status": "FAILED", "message": "No quarterly factors to evaluate"}

        all_factor_ids = [f.factor_id for f in factors]

        # 计算日期范围：以最新交易日作为评估日
        ref_trade_date = await TradeCalendar.get_latest_trade_date()
        if ref_trade_date is None:
            logger.warning("[factor.evaluate_quarterly] 交易日历查询失败，回退使用 date.today()")
            ref_trade_date = date.today()

        if not end_date:
            end_date = ref_trade_date.strftime("%Y-%m-%d")
        if not start_date:
            # 季频评估需要更长历史（7年 ≈ 28季度，覆盖 20Q 窗口）
            start = ref_trade_date - timedelta(days=_RETENTION_YEARS * 365)
            start_date = start.strftime("%Y-%m-%d")

        logger.info(
            "[factor.evaluate_quarterly] === 开始季频评估 === pools=%d factors=%d range=%s~%s",
            len(pools), len(all_factor_ids), start_date, end_date,
        )

        # 初始化服务
        reader = CrossSectionReader()
        ic_calc = ICCalculator()
        backtester = LayeredBacktester()
        grade_eval = GradeEvaluator()

        # 逐样本池评估
        total_stats = 0
        start_dt = date.fromisoformat(start_date)
        end_dt = date.fromisoformat(end_date)
        total_pools = len(pools)
        evaluated_pool_ids: list[str] = []

        for pool_idx, pool in enumerate(pools, 1):
            pool_factor_ids = await PoolInitService.resolve_factor_ids(pool, all_factor_ids)
            logger.info(
                "[factor.evaluate_quarterly] >>> 池进度 %d/%d pool=%s factors=%d (累计耗时=%.1fs)",
                pool_idx, total_pools, pool.pool_id, len(pool_factor_ids),
                time.monotonic() - task_start_time,
            )

            pool_start = time.monotonic()
            count = await self._evaluate_pool(
                pool=pool,
                factor_ids=pool_factor_ids,
                start_date=start_dt,
                end_date=end_dt,
                today=ref_trade_date,
                reader=reader,
                ic_calc=ic_calc,
                backtester=backtester,
                grade_eval=grade_eval,
            )
            pool_elapsed = time.monotonic() - pool_start
            total_stats += count
            evaluated_pool_ids.append(pool.pool_id)

            logger.info(
                "[factor.evaluate_quarterly] <<< 池完成 %d/%d pool=%s 成功=%d/%d 耗时=%.1fs "
                "累计stats=%d 累计耗时=%.1fs",
                pool_idx, total_pools, pool.pool_id, count, len(pool_factor_ids),
                pool_elapsed, total_stats, time.monotonic() - task_start_time,
            )

        total_elapsed = time.monotonic() - task_start_time
        logger.info(
            "[factor.evaluate_quarterly] === 任务完成 === total_stats=%d factors=%d pools=%s 总耗时=%.1fs",
            total_stats, len(all_factor_ids), evaluated_pool_ids, total_elapsed,
        )

        return {
            "status": "SUCCESS",
            "total_stats": total_stats,
            "factors_evaluated": len(all_factor_ids),
            "pools": evaluated_pool_ids,
        }

    async def _evaluate_pool(
        self,
        pool: FacFactorPool,
        factor_ids: list[str],
        start_date: date,
        end_date: date,
        today: date,
        reader: CrossSectionReader,
        ic_calc: ICCalculator,
        backtester: LayeredBacktester,
        grade_eval: GradeEvaluator,
    ) -> int:
        """评估单个样本池的所有季频因子（生产者-消费者并发模式）。"""
        pool_id = pool.pool_id
        total_factors = len(factor_ids)
        pool_t0 = time.monotonic()
        logger.info(
            "[factor.evaluate_quarterly] >>> 进入样本池: %s (%s) factors=%d concurrency=%d",
            pool_id, pool.pool_name, total_factors, _QUARTERLY_EVAL_CONCURRENCY,
        )

        # 预加载共享只读数据
        t0 = time.monotonic()
        symbols = await reader.load_pool_symbols(pool_id)
        logger.info(
            "[factor.evaluate_quarterly] pool=%s 标的加载完成: %d 只 耗时=%.2fs",
            pool_id, len(symbols), time.monotonic() - t0,
        )
        if not symbols:
            logger.warning("[factor.evaluate_quarterly] 样本池 %s 无标的，跳过", pool_id)
            return 0

        t0 = time.monotonic()
        industry_map = await reader.load_industry_map(symbols)
        logger.info(
            "[factor.evaluate_quarterly] pool=%s 行业映射加载: %d 条 耗时=%.2fs",
            pool_id, len(industry_map), time.monotonic() - t0,
        )

        t0 = time.monotonic()
        market_cap_panel = await reader.load_market_cap_panel(symbols, start_date, end_date)
        logger.info(
            "[factor.evaluate_quarterly] pool=%s 市值面板加载: rows=%d 耗时=%.2fs",
            pool_id, len(market_cap_panel) if market_cap_panel is not None else 0,
            time.monotonic() - t0,
        )

        t0 = time.monotonic()
        membership = await reader.build_pool_membership(pool_id, start_date, end_date)
        logger.info(
            "[factor.evaluate_quarterly] pool=%s membership 构建: %d 期 耗时=%.2fs",
            pool_id, len(membership) if membership else 0, time.monotonic() - t0,
        )

        # 加载收益率面板（季频 horizon: 63/126/252 交易日 = 1Q/2Q/4Q）
        t0 = time.monotonic()
        returns_panel = await reader.load_returns_panel(
            start_date=start_date, end_date=end_date, symbols=symbols,
            horizons=_Q_HORIZONS,
        )
        returns_panel = reader.filter_panel_by_membership(returns_panel, membership)
        logger.info(
            "[factor.evaluate_quarterly] pool=%s 收益率面板加载: rows=%d 耗时=%.2fs",
            pool_id, len(returns_panel), time.monotonic() - t0,
        )
        if returns_panel.empty:
            logger.warning("[factor.evaluate_quarterly] 样本池 %s 收益率数据为空，跳过", pool_id)
            return 0

        # 预加载因子方向和数据起始日期
        t0 = time.monotonic()
        direction_map, data_start_map = await self._load_factor_metadata(factor_ids)
        logger.info(
            "[factor.evaluate_quarterly] pool=%s 因子元数据加载: %d 条 耗时=%.2fs",
            pool_id, len(direction_map), time.monotonic() - t0,
        )

        logger.info(
            "[factor.evaluate_quarterly] pool=%s 共享数据预加载完成 总耗时=%.2fs, 开始并发评估 %d 因子",
            pool_id, time.monotonic() - pool_t0, total_factors,
        )

        # 构建共享上下文
        ctx = _QuarterlyEvalContext(
            pool_id=pool_id,
            symbols=symbols,
            industry_map=industry_map,
            market_cap_panel=market_cap_panel,
            membership=membership,
            returns_panel=returns_panel,
            direction_map=direction_map,
            data_start_map=data_start_map,
            reader=reader,
            ic_calc=ic_calc,
            backtester=backtester,
            grade_eval=grade_eval,
            start_date=start_date,
            end_date=end_date,
            today=today,
            pool_start_time=pool_t0,
        )

        # 生产者-消费者并发评估
        runner = ConcurrentRunner[str, dict](
            concurrency=_QUARTERLY_EVAL_CONCURRENCY,
            log_name=f"factor.evaluate_quarterly[{pool_id}]",
        )
        eval_t0 = time.monotonic()
        result = await runner.run_items(
            items=factor_ids,
            processor=lambda fid: self._evaluate_single_factor(fid, ctx),
        )
        eval_elapsed = time.monotonic() - eval_t0

        avg_per_factor = eval_elapsed / total_factors if total_factors > 0 else 0.0
        logger.info(
            "[factor.evaluate_quarterly] <<< 样本池 %s 评估完成: 成功=%d/%d 失败=%d "
            "并发评估=%.1fs (平均%.1fs/因子) 池总耗时=%.1fs",
            pool_id, result.success_count, total_factors,
            result.failure_count, eval_elapsed, avg_per_factor,
            time.monotonic() - pool_t0,
        )
        return result.success_count

    async def _evaluate_single_factor(
        self, factor_id: str, ctx: _QuarterlyEvalContext,
    ) -> dict[str, Any] | None:
        """单个季频因子完整评估：加载 PIT 面板 → 计算 stats → 持久化。"""
        reader = ctx.reader
        factor_t0 = time.monotonic()
        logger.info(
            "[factor.evaluate_quarterly] pool=%s >>> 开始评估 factor=%s",
            ctx.pool_id, factor_id,
        )

        # 因子级 start_date
        factor_data_start = ctx.data_start_map.get(factor_id)
        effective_start = max(ctx.start_date, factor_data_start) if factor_data_start else ctx.start_date

        # 加载 PIT 财务因子面板（前向填充到日频 + 截面预处理）
        t0 = time.monotonic()
        factor_panel = await reader.load_single_factor_panel(
            start_date=effective_start,
            end_date=ctx.end_date,
            pool_id=ctx.pool_id,
            symbols=ctx.symbols,
            factor_id=factor_id,
            industry_map=ctx.industry_map,
            market_cap_panel=ctx.market_cap_panel,
        )
        factor_panel = reader.filter_panel_by_membership(factor_panel, ctx.membership)
        logger.info(
            "[factor.evaluate_quarterly] pool=%s factor=%s 面板加载完成: rows=%d 耗时=%.2fs",
            ctx.pool_id, factor_id, len(factor_panel), time.monotonic() - t0,
        )

        if factor_panel.empty or factor_id not in factor_panel.columns:
            logger.info(
                "[factor.evaluate_quarterly] pool=%s factor=%s 数据为空，跳过 耗时=%.2fs",
                ctx.pool_id, factor_id, time.monotonic() - factor_t0,
            )
            return None

        single_factor = factor_panel[[factor_id]]

        # 数据门禁
        total_cells = len(single_factor)
        non_null = int(single_factor[factor_id].notna().sum())
        coverage = float(non_null / total_cells) if total_cells > 0 else 0.0

        if total_cells < _MIN_FACTOR_ROWS:
            logger.warning(
                "[factor.evaluate_quarterly] pool=%s factor=%s 门禁拦截: 数据量不足 rows=%d < 阈值=%d，跳过",
                ctx.pool_id, factor_id, total_cells, _MIN_FACTOR_ROWS,
            )
            return None

        if coverage < _MIN_COVERAGE:
            logger.warning(
                "[factor.evaluate_quarterly] pool=%s factor=%s 门禁拦截: 覆盖率不足 coverage=%.2f < 阈值=%.2f，跳过",
                ctx.pool_id, factor_id, coverage, _MIN_COVERAGE,
            )
            return None

        factor_values = single_factor[factor_id].dropna()
        if np.isinf(factor_values).any():
            logger.warning(
                "[factor.evaluate_quarterly] pool=%s factor=%s 门禁拦截: 存在 Infinity 值，跳过",
                ctx.pool_id, factor_id,
            )
            return None

        # 应用因子方向
        if ctx.direction_map.get(factor_id, "DESC") == "ASC":
            single_factor = single_factor.copy()
            single_factor[factor_id] = -single_factor[factor_id]

        # 预计算 IC 序列（1Q/2Q/4Q horizon）
        t_pre = time.monotonic()
        all_ic_series = ctx.ic_calc.calc_all_ic_series(
            single_factor, ctx.returns_panel, horizons=_Q_HORIZONS,
        )
        ic_series_1q = all_ic_series.get(63, pd.Series(dtype=float, name="ic_63d"))
        multi_ic_series = {
            h: all_ic_series[h] for h in (126, 252) if h in all_ic_series
        }
        turnover = ctx.ic_calc.calc_turnover(single_factor)
        ic_decay_curve, decay_half_life = ctx.ic_calc.calc_decay_info(
            single_factor, ctx.returns_panel,
        )
        pre_elapsed = time.monotonic() - t_pre
        logger.info(
            "[factor.evaluate_quarterly] pool=%s factor=%s 预计算完成: ic_1q_n=%d "
            "turnover=%.4f decay_half_life=%s 耗时=%.2fs",
            ctx.pool_id, factor_id, len(ic_series_1q),
            turnover or 0.0, decay_half_life, pre_elapsed,
        )

        # 窗口循环：8Q/12Q/16Q/20Q
        t_win = time.monotonic()
        window_results: list[dict[str, Any]] = []
        for ann_window, trade_window in _QUARTERLY_WINDOWS.items():
            stats = self._calc_quarterly_window_stats(
                ann_window=ann_window,
                trade_window=trade_window,
                ic_series_1q=ic_series_1q,
                multi_ic_series=multi_ic_series,
                factor_panel=single_factor,
                returns_panel=ctx.returns_panel,
                turnover=turnover,
                ic_decay_curve=ic_decay_curve,
                decay_half_life=decay_half_life,
                ic_calc=ctx.ic_calc,
                backtester=ctx.backtester,
            )
            stats["factor_id"] = factor_id
            stats["pool_id"] = ctx.pool_id
            stats["calc_date"] = ctx.today
            stats["ann_window"] = ann_window
            stats["coverage"] = coverage

            # 评定等级
            grade = ctx.grade_eval.evaluate(stats)
            stats["factor_grade"] = grade
            window_results.append(stats)

        logger.info(
            "[factor.evaluate_quarterly] pool=%s factor=%s 多窗口 stats 计算完成 windows=%d 耗时=%.2fs",
            ctx.pool_id, factor_id, len(window_results), time.monotonic() - t_win,
        )

        # 持久化
        models = [self._build_stats_model(s) for s in window_results]
        await FacFinancialFactorStats.bulk_create_or_update(
            models,
            on_conflict=["factor_id", "pool_id", "calc_date", "ann_window"],
            update_fields=[
                "ic_mean", "ic_std", "icir", "ic_win_rate",
                "ic_mean_2q", "ic_mean_4q",
                "ic_tstat", "ic_pvalue",
                "turnover", "decay_half_life",
                "long_short_annual_ret", "long_short_sharpe",
                "group_returns", "ic_decay_curve",
                "coverage", "factor_grade",
            ],
        )

        primary_stats = next(
            (s for s in window_results if s["ann_window"] == 20), window_results[0],
        )
        logger.info(
            "[factor.evaluate_quarterly] pool=%s factor=%s <<< 评估完成 windows=%d grades=%s "
            "icir_20Q=%.3f coverage=%.2f 总耗时=%.2fs",
            ctx.pool_id, factor_id, len(window_results),
            {s["ann_window"]: s["factor_grade"] for s in window_results},
            primary_stats.get("icir", 0) or 0, primary_stats.get("coverage", 0) or 0,
            time.monotonic() - factor_t0,
        )
        return primary_stats

    @staticmethod
    async def _load_factor_metadata(
        factor_ids: list[str],
    ) -> tuple[dict[str, str], dict[str, date | None]]:
        """批量加载因子方向和数据起始日期。"""
        if not factor_ids:
            return {}, {}
        rows = await FacFactorRegistry.filter(factor_id__in=factor_ids)
        direction_map = {r.factor_id: (r.direction or "DESC") for r in rows}
        data_start_map = {r.factor_id: r.data_start_date for r in rows}
        return direction_map, data_start_map

    @staticmethod
    def _calc_quarterly_window_stats(
        ann_window: int,
        trade_window: int,
        ic_series_1q: Any,
        multi_ic_series: dict[int, Any],
        factor_panel: Any,
        returns_panel: Any,
        turnover: float | None,
        ic_decay_curve: list[dict[str, Any]],
        decay_half_life: float | None,
        ic_calc: ICCalculator,
        backtester: LayeredBacktester,
    ) -> dict[str, Any]:
        """计算单个季频窗口的 stats。

        Args:
            ann_window: 季度数（8/12/16/20）
            trade_window: 对应的交易日数（504/756/1008/1260）
        """
        # IC 截面统计（按末 trade_window 日截取 IC 序列）
        ic_stats = ic_calc.calc_ic_stats(ic_series_1q, window=trade_window)
        ic_sig = ic_calc.calc_ic_significance(ic_series_1q, window=trade_window)
        # multi_ic: {126: ic_series, 252: ic_series} → 字段名 ic_mean_126d/ic_mean_252d
        multi_ic = ic_calc.calc_multi_horizon_ic_stats(multi_ic_series, window=trade_window)

        # 分层回测（季频用 1Q horizon 列与 4 倍年化因子）
        backtest_result = backtester.run(
            factor_panel, returns_panel,
            window=trade_window,
            returns_column=_Q_BACKTEST_RETURNS_COLUMN,
            annualization_factor=_Q_ANNUALIZATION_FACTOR,
        )

        return {
            "ic_mean": ic_stats.get("ic_mean"),
            "ic_std": ic_stats.get("ic_std"),
            "icir": ic_stats.get("icir"),
            "ic_win_rate": ic_stats.get("ic_win_rate"),
            # 字段映射：126d → 2Q, 252d → 4Q
            "ic_mean_2q": multi_ic.get("ic_mean_126d"),
            "ic_mean_4q": multi_ic.get("ic_mean_252d"),
            "ic_tstat": ic_sig.get("ic_tstat"),
            "ic_pvalue": ic_sig.get("ic_pvalue"),
            "long_short_annual_ret": backtest_result.get("long_short_annual_ret"),
            "long_short_sharpe": backtest_result.get("long_short_sharpe"),
            "group_returns": backtest_result.get("group_returns"),
            "turnover": turnover,
            "decay_half_life": decay_half_life,
            "ic_decay_curve": ic_decay_curve,
        }

    @staticmethod
    def _to_native_float(value: Any) -> float | None:
        """将 numpy/pandas 数值类型转为 Python 原生 float。"""
        if value is None:
            return None
        try:
            v = float(value)
            return None if np.isnan(v) or np.isinf(v) else v
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _build_stats_model(stats: dict[str, Any]) -> FacFinancialFactorStats:
        """从统计字典构建 FacFinancialFactorStats 模型实例。"""
        _f = FactorEvaluateQuarterlyTask._to_native_float
        return FacFinancialFactorStats(
            factor_id=stats["factor_id"],
            pool_id=stats["pool_id"],
            calc_date=stats["calc_date"],
            ann_window=stats["ann_window"],
            ic_mean=_f(stats.get("ic_mean")),
            ic_std=_f(stats.get("ic_std")),
            icir=_f(stats.get("icir")),
            ic_win_rate=_f(stats.get("ic_win_rate")),
            ic_mean_2q=_f(stats.get("ic_mean_2q")),
            ic_mean_4q=_f(stats.get("ic_mean_4q")),
            ic_tstat=_f(stats.get("ic_tstat")),
            ic_pvalue=_f(stats.get("ic_pvalue")),
            long_short_annual_ret=_f(stats.get("long_short_annual_ret")),
            long_short_sharpe=_f(stats.get("long_short_sharpe")),
            group_returns=stats.get("group_returns"),
            turnover=_f(stats.get("turnover")),
            decay_half_life=_f(stats.get("decay_half_life")),
            coverage=_f(stats.get("coverage")),
            factor_grade=stats.get("factor_grade"),
            ic_decay_curve=stats.get("ic_decay_curve"),
        )
