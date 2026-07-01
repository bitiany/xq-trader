"""周频因子评估任务 — 按样本池计算 IC/ICIR/分层回测/换手率/衰减半衰期，评定因子等级。

评估流程（生产者-消费者并发模式）：
  1. 从 fac_factor_pool 读取样本池配置（含 factor_scope）
  2. 从 fac_factor_registry 读取活跃因子列表
  3. 逐样本池：预加载共享只读数据 → ConcurrentRunner 并发评估各因子 → 即时持久化
  4. 更新因子注册表的全局等级

并发设计：
  - 各因子相互独立，通过 ConcurrentRunner 多消费者并发评估
  - 共享只读数据（symbols/returns_panel/industry_map 等）预加载一次
  - 单因子失败不影响其他，错误隔离
  - 内存峰值 = N 个因子同时驻留（N=concurrency），非全量因子
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np

from framework.commons.concurrent import ConcurrentRunner
from framework.commons.logger import get_logger
from framework.scheduler.base_task import BaseTask
from worker.plugins.utils import parse_list_param
from xqtrader.domain.factor.models.factor_pool import FacFactorPool
from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry
from xqtrader.domain.factor.models.factor_stats import FacFactorStats
from xqtrader.domain.factor.services.cross_section_reader import CrossSectionReader
from xqtrader.domain.factor.services.grade_evaluator import GradeEvaluator
from xqtrader.domain.factor.services.ic_calculator import ICCalculator
from xqtrader.domain.factor.services.layered_backtest import LayeredBacktester
from xqtrader.domain.factor.services.pool_init import PoolInitService
from xqtrader.domain.factor.services.registry import (
    auto_discover_factors,
    register_factor_variants,
    sync_to_registry,
)

logger = get_logger("factor.evaluate")

_RETENTION_YEARS = 5
_DEFAULT_WINDOW = 504  # IC 统计窗口（约 2 年），平衡近期表现与统计稳定性
_EVAL_CONCURRENCY = 12  # 评估任务消费者数量（stock 连接池 20+30=50，12×2=24 ≤ 50，余量充足）

# 不参与评估的因子类别：
# - return: 评估标签（fwd_ret_*），不评估
# - chanlun: 非截面连续值（缠论笔数等），覆盖率仅6%，IC异常，不入因子评估和合成
# - composite_group/composite_cross: 合成产物，不评估
# - interaction: 交互因子，合成产物，不评估
_EXCLUDED_CATEGORIES: tuple[str, ...] = (
    "return", "chanlun", "composite_group", "composite_cross", "interaction",
)

# 因子数据门禁阈值
_MIN_FACTOR_ROWS = 1000  # 最少有效数据行数（低于此值视为数据不完整）
_MIN_COVERAGE = 0.80  # 最低覆盖率阈值（80%）


@dataclass(frozen=True)
class _EvalContext:
    """单因子评估的共享只读上下文（所有消费者共用，不可变）。"""

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
    window: int
    today: date


class FactorEvaluateTask(BaseTask):
    """周频因子评估任务。"""

    task_name = "factor.evaluate_weekly"
    description = "按样本池计算因子统计指标并评定等级"
    prevent_concurrent = True

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        task_start_time = time.monotonic()
        pool_ids = parse_list_param(kwargs.get("pool_ids"))
        factor_ids = parse_list_param(kwargs.get("factor_ids"))
        start_date = str(kwargs.get("start_date", ""))
        end_date = str(kwargs.get("end_date", ""))
        window = int(kwargs.get("window", _DEFAULT_WINDOW))

        logger.info("[factor.evaluate] === 任务启动 === params: pool_ids=%s factor_ids=%s window=%d",
                    pool_ids, factor_ids, window)

        # 同步默认样本池配置（含 status 收敛至 active 池集合）
        t0 = time.monotonic()
        await PoolInitService().sync_default_pools()
        logger.info("[factor.evaluate] 样本池同步完成 耗时=%.2fs", time.monotonic() - t0)

        # 加载因子插件并同步注册表到 DB（确保 draft 因子被激活为 active）
        t0 = time.monotonic()
        auto_discover_factors()
        register_factor_variants()
        await sync_to_registry()
        logger.info("[factor.evaluate] 因子插件发现+注册表同步完成 耗时=%.2fs", time.monotonic() - t0)

        # 从 DB 加载样本池配置
        if pool_ids:
            pools = await FacFactorPool.filter(
                pool_id__in=pool_ids,
                status="active",
            )
        else:
            pools = await FacFactorPool.filter(status="active")

        if not pools:
            return {"status": "FAILED", "message": "No active pools found"}

        # 解析全量活跃因子列表
        # 排除：return(评估标签) / chanlun(非截面连续值) / composite_*(合成产物) / interaction(交互因子)
        excluded_set = set(_EXCLUDED_CATEGORIES)
        if factor_ids:
            all_factors = await FacFactorRegistry.filter(
                factor_id__in=factor_ids,
                status="active",
            )
        else:
            all_factors = await FacFactorRegistry.filter(status="active")
        factors = [f for f in all_factors if f.category not in excluded_set]

        if not factors:
            return {"status": "FAILED", "message": "No active factors to evaluate"}

        all_factor_ids = [f.factor_id for f in factors]

        # 计算日期范围
        if not end_date:
            end_date = date.today().strftime("%Y-%m-%d")
        if not start_date:
            start = date.today() - timedelta(days=_RETENTION_YEARS * 365)
            start_date = start.strftime("%Y-%m-%d")

        logger.info(
            "[factor.evaluate] === 开始全量评估 === pools=%d factors=%d range=%s~%s window=%d",
            len(pools), len(all_factor_ids), start_date, end_date, window,
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
            # 根据样本池的 factor_scope 解析实际评估的因子
            pool_factor_ids = await PoolInitService.resolve_factor_ids(pool, all_factor_ids)
            logger.info(
                "[factor.evaluate] >>> 池进度 %d/%d pool=%s factors=%d",
                pool_idx, total_pools, pool.pool_id, len(pool_factor_ids),
            )

            pool_start = time.monotonic()
            count = await self._evaluate_pool(
                pool=pool,
                factor_ids=pool_factor_ids,
                start_date=start_dt,
                end_date=end_dt,
                window=window,
                reader=reader,
                ic_calc=ic_calc,
                backtester=backtester,
                grade_eval=grade_eval,
            )
            pool_elapsed = time.monotonic() - pool_start
            total_stats += count
            evaluated_pool_ids.append(pool.pool_id)
            logger.info(
                "[factor.evaluate] <<< 池完成 %d/%d pool=%s 成功=%d/%d 耗时=%.1fs 累计耗时=%.1fs",
                pool_idx, total_pools, pool.pool_id, count, len(pool_factor_ids),
                pool_elapsed, time.monotonic() - task_start_time,
            )

        # 更新因子注册表全局等级
        t0 = time.monotonic()
        await self._update_global_grades(all_factor_ids, evaluated_pool_ids)
        logger.info("[factor.evaluate] 全局等级更新完成 耗时=%.2fs", time.monotonic() - t0)

        total_elapsed = time.monotonic() - task_start_time
        logger.info(
            "[factor.evaluate] === 任务完成 === total_stats=%d factors=%d pools=%s 总耗时=%.1fs",
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
        window: int,
        reader: CrossSectionReader,
        ic_calc: ICCalculator,
        backtester: LayeredBacktester,
        grade_eval: GradeEvaluator,
    ) -> int:
        """评估单个样本池的所有因子（生产者-消费者并发模式）。

        各因子相互独立，通过 ConcurrentRunner 并发评估：
        - 预加载共享只读数据（symbols/returns_panel 等）
        - N 个消费者并发处理各因子（加载面板→计算 stats→持久化）
        - 单因子失败不影响其他，错误隔离
        """
        pool_id = pool.pool_id
        total_factors = len(factor_ids)
        pool_t0 = time.monotonic()
        logger.info(
            "[factor.evaluate] >>> 进入样本池: %s (%s) factors=%d concurrency=%d",
            pool_id, pool.pool_name, total_factors, _EVAL_CONCURRENCY,
        )

        # 预加载共享只读数据（所有因子共用）
        t0 = time.monotonic()
        symbols = await reader.load_pool_symbols(pool_id)
        logger.info(
            "[factor.evaluate] pool=%s 标的加载完成: %d 只 耗时=%.2fs",
            pool_id, len(symbols), time.monotonic() - t0,
        )
        if not symbols:
            logger.warning("[factor.evaluate] 样本池 %s 无标的，跳过", pool_id)
            return 0

        t0 = time.monotonic()
        industry_map = await reader.load_industry_map(symbols)
        logger.info(
            "[factor.evaluate] pool=%s 行业映射加载: %d 条 耗时=%.2fs",
            pool_id, len(industry_map), time.monotonic() - t0,
        )

        t0 = time.monotonic()
        market_cap_panel = await reader.load_market_cap_panel(symbols, start_date, end_date)
        logger.info(
            "[factor.evaluate] pool=%s 市值面板加载: rows=%d 耗时=%.2fs",
            pool_id, len(market_cap_panel) if market_cap_panel is not None else 0,
            time.monotonic() - t0,
        )

        t0 = time.monotonic()
        membership = await reader.build_pool_membership(pool_id, start_date, end_date)
        logger.info(
            "[factor.evaluate] pool=%s membership 构建: %d 期 耗时=%.2fs",
            pool_id, len(membership) if membership else 0, time.monotonic() - t0,
        )

        t0 = time.monotonic()
        returns_panel = await reader.load_returns_panel(
            start_date=start_date, end_date=end_date, symbols=symbols,
        )
        returns_panel = reader.filter_panel_by_membership(returns_panel, membership)
        logger.info(
            "[factor.evaluate] pool=%s 收益率面板加载: rows=%d 耗时=%.2fs",
            pool_id, len(returns_panel), time.monotonic() - t0,
        )
        if returns_panel.empty:
            logger.warning("[factor.evaluate] 样本池 %s 收益率数据为空，跳过", pool_id)
            return 0

        # 预加载因子方向（DESC/ASC）和数据起始日期：ASC 因子需翻转符号使"高值→高收益"成立
        t0 = time.monotonic()
        direction_map, data_start_map = await self._load_factor_metadata(factor_ids)
        logger.info(
            "[factor.evaluate] pool=%s 因子元数据加载: %d 条 耗时=%.2fs",
            pool_id, len(direction_map), time.monotonic() - t0,
        )

        logger.info(
            "[factor.evaluate] pool=%s 共享数据预加载完成 总耗时=%.2fs, 开始并发评估 %d 因子",
            pool_id, time.monotonic() - pool_t0, total_factors,
        )

        # 构建共享上下文（只读，所有消费者共用）
        ctx = _EvalContext(
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
            window=window,
            today=date.today(),
        )

        # 生产者-消费者并发评估
        runner = ConcurrentRunner[str, dict](
            concurrency=_EVAL_CONCURRENCY,
            log_name=f"factor.evaluate[{pool_id}]",
        )
        result = await runner.run_items(
            items=factor_ids,
            processor=lambda fid: self._evaluate_single_factor(fid, ctx),
        )

        logger.info(
            "[factor.evaluate] <<< 样本池 %s 评估完成: 成功=%d/%d 失败=%d 耗时=%.1fs",
            pool_id, result.success_count, total_factors,
            result.failure_count, time.monotonic() - pool_t0,
        )
        return result.success_count

    async def _evaluate_single_factor(
        self, factor_id: str, ctx: _EvalContext,
    ) -> dict[str, Any] | None:
        """单个因子完整评估：加载面板 → 计算 stats → 持久化。

        各消费者独立调用此方法，因子间无共享可变状态。
        返回 None 表示因子数据为空被跳过；返回 stats dict 表示评估成功。
        """
        reader = ctx.reader
        factor_t0 = time.monotonic()
        logger.info(
            "[factor.evaluate] pool=%s >>> 开始评估 factor=%s",
            ctx.pool_id, factor_id,
        )

        # 加载单因子截面面板（含截面预处理：缺失值填充→MAD→Z-score→行业+市值中性化→再Z-score）
        # 因子级 start_date：受数据源限制的因子（如 fund_flow 自 2023-09-11 起）使用自身起始日期，
        # 避免在 5 年默认窗口中因覆盖率不足 80% 被门禁拦截
        factor_data_start = ctx.data_start_map.get(factor_id)
        effective_start = max(ctx.start_date, factor_data_start) if factor_data_start else ctx.start_date

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
            "[factor.evaluate] pool=%s factor=%s 面板加载完成: rows=%d 耗时=%.2fs",
            ctx.pool_id, factor_id, len(factor_panel), time.monotonic() - t0,
        )

        if factor_panel.empty or factor_id not in factor_panel.columns:
            logger.info(
                "[factor.evaluate] pool=%s factor=%s 数据为空，跳过 耗时=%.2fs",
                ctx.pool_id, factor_id, time.monotonic() - factor_t0,
            )
            return None

        single_factor = factor_panel[[factor_id]]

        # 数据门禁管控：评估前必须确认因子数据完整，避免无数据或不完整数据导致评估报错
        total_cells = len(single_factor)
        non_null = int(single_factor[factor_id].notna().sum())
        coverage = float(non_null / total_cells) if total_cells > 0 else 0.0

        if total_cells < _MIN_FACTOR_ROWS:
            logger.warning(
                "[factor.evaluate] pool=%s factor=%s 门禁拦截: 数据量不足 rows=%d < 阈值=%d，跳过 耗时=%.2fs",
                ctx.pool_id, factor_id, total_cells, _MIN_FACTOR_ROWS,
                time.monotonic() - factor_t0,
            )
            return None

        if coverage < _MIN_COVERAGE:
            logger.warning(
                "[factor.evaluate] pool=%s factor=%s 门禁拦截: 覆盖率不足 coverage=%.2f < 阈值=%.2f，跳过 耗时=%.2fs",
                ctx.pool_id, factor_id, coverage, _MIN_COVERAGE,
                time.monotonic() - factor_t0,
            )
            return None

        # 检查 Infinity 值（会导致后续统计计算报错）
        factor_values = single_factor[factor_id].dropna()
        if np.isinf(factor_values).any():
            logger.warning(
                "[factor.evaluate] pool=%s factor=%s 门禁拦截: 存在 Infinity 值，跳过 耗时=%.2fs",
                ctx.pool_id, factor_id, time.monotonic() - factor_t0,
            )
            return None

        # 应用因子方向：ASC 表示因子值越小越好，翻转符号使所有因子统一为"高值→高收益"
        if ctx.direction_map.get(factor_id, "DESC") == "ASC":
            single_factor = single_factor.copy()
            single_factor[factor_id] = -single_factor[factor_id]

        # 计算统计指标
        t0 = time.monotonic()
        stats = self._calc_factor_stats(
            factor_id=factor_id,
            factor_panel=single_factor,
            returns_panel=ctx.returns_panel,
            window=ctx.window,
            ic_calc=ctx.ic_calc,
            backtester=ctx.backtester,
        )
        logger.info(
            "[factor.evaluate] pool=%s factor=%s stats 计算完成 耗时=%.2fs",
            ctx.pool_id, factor_id, time.monotonic() - t0,
        )

        stats["factor_id"] = factor_id
        stats["pool_id"] = ctx.pool_id
        stats["calc_date"] = ctx.today
        stats["window"] = ctx.window
        stats["coverage"] = coverage  # 复用门禁检查中已计算的覆盖度

        # 评定等级
        grade = ctx.grade_eval.evaluate(stats)
        stats["factor_grade"] = grade

        # 即时持久化（单因子）
        t0 = time.monotonic()
        model = self._build_stats_model(stats)
        await FacFactorStats.bulk_create_or_update(
            [model],
            on_conflict=["factor_id", "pool_id", "calc_date", "window"],
            update_fields=[
                "ic_mean", "ic_std", "icir", "ic_win_rate",
                "ic_mean_5d", "ic_mean_10d", "ic_mean_20d",
                "ic_tstat", "ic_pvalue",
                "turnover", "decay_half_life",
                "long_short_annual_ret", "long_short_sharpe",
                "group_returns", "ic_decay_curve",
                "coverage", "factor_grade",
            ],
        )

        logger.info(
            "[factor.evaluate] pool=%s factor=%s <<< 评估完成 grade=%s icir=%.3f "
            "coverage=%.2f 持久化=%.2fs 总耗时=%.2fs",
            ctx.pool_id, factor_id, grade,
            stats.get("icir", 0) or 0, stats.get("coverage", 0) or 0,
            time.monotonic() - t0, time.monotonic() - factor_t0,
        )
        return stats

    @staticmethod
    async def _load_factor_metadata(
        factor_ids: list[str],
    ) -> tuple[dict[str, str], dict[str, date | None]]:
        """批量加载因子方向（DESC/ASC）和数据起始日期。

        Args:
            factor_ids: 因子 ID 列表

        Returns:
            (direction_map, data_start_map)
            - direction_map: {factor_id: direction}，缺失 direction 视为 DESC
            - data_start_map: {factor_id: data_start_date}，NULL 表示无限制
        """
        if not factor_ids:
            return {}, {}
        rows = await FacFactorRegistry.filter(factor_id__in=factor_ids)
        direction_map = {r.factor_id: (r.direction or "DESC") for r in rows}
        data_start_map = {r.factor_id: r.data_start_date for r in rows}
        return direction_map, data_start_map

    @staticmethod
    def _calc_factor_stats(
        factor_id: str,
        factor_panel: Any,
        returns_panel: Any,
        window: int,
        ic_calc: ICCalculator,
        backtester: LayeredBacktester,
    ) -> dict[str, Any]:
        """计算单个因子的统计指标。"""
        # IC 序列与统计
        ic_series = ic_calc.calc_ic_series(factor_panel, returns_panel, window=window)
        ic_stats = ic_calc.calc_ic_stats(ic_series, window=window)
        ic_sig = ic_calc.calc_ic_significance(ic_series, window=window)
        multi_ic = ic_calc.calc_multi_horizon_ic(
            factor_panel, returns_panel, window=window,
        )

        # 分层回测
        backtest_result = backtester.run(factor_panel, returns_panel)

        # 换手率
        turnover = ic_calc.calc_turnover(factor_panel)

        # IC 衰减曲线（持久化为 JSONB，供前端绘制衰减图）与半衰期（共享底层计算）
        ic_decay_curve = ic_calc.calc_ic_decay_curve(factor_panel, returns_panel)
        decay_half_life = ic_calc.calc_decay_half_life(factor_panel, returns_panel)

        return {
            "ic_mean": ic_stats.get("ic_mean"),
            "ic_std": ic_stats.get("ic_std"),
            "icir": ic_stats.get("icir"),
            "ic_win_rate": ic_stats.get("ic_win_rate"),
            "ic_mean_5d": multi_ic.get("ic_mean_5d"),
            "ic_mean_10d": multi_ic.get("ic_mean_10d"),
            "ic_mean_20d": multi_ic.get("ic_mean_20d"),
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
        """将 numpy/pandas 数值类型转为 Python 原生 float，避免 SQLAlchemy 序列化报错。"""
        if value is None:
            return None
        try:
            v = float(value)
            return None if np.isnan(v) or np.isinf(v) else v
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _build_stats_model(stats: dict[str, Any]) -> FacFactorStats:
        """从统计字典构建 FacFactorStats 模型实例。"""
        _f = FactorEvaluateTask._to_native_float
        return FacFactorStats(
            factor_id=stats["factor_id"],
            pool_id=stats["pool_id"],
            calc_date=stats["calc_date"],
            window=stats["window"],
            ic_mean=_f(stats.get("ic_mean")),
            ic_std=_f(stats.get("ic_std")),
            icir=_f(stats.get("icir")),
            ic_win_rate=_f(stats.get("ic_win_rate")),
            ic_mean_5d=_f(stats.get("ic_mean_5d")),
            ic_mean_10d=_f(stats.get("ic_mean_10d")),
            ic_mean_20d=_f(stats.get("ic_mean_20d")),
            ic_tstat=_f(stats.get("ic_tstat")),
            ic_pvalue=_f(stats.get("ic_pvalue")),
            turnover=_f(stats.get("turnover")),
            decay_half_life=_f(stats.get("decay_half_life")),
            long_short_annual_ret=_f(stats.get("long_short_annual_ret")),
            long_short_sharpe=_f(stats.get("long_short_sharpe")),
            group_returns=stats.get("group_returns") or {},
            ic_decay_curve=stats.get("ic_decay_curve") or [],
            coverage=_f(stats.get("coverage")),
            factor_grade=stats.get("factor_grade"),
        )

    @staticmethod
    async def _update_global_grades(factor_ids: list[str], pool_ids: list[str]) -> None:
        """更新因子注册表的全局等级（最优样本池规则）。"""
        grade_eval = GradeEvaluator()
        total = len(factor_ids)
        updated = 0
        logger.info(
            "[factor.evaluate] 开始更新全局等级: factors=%d pools=%s", total, pool_ids,
        )

        for idx, factor_id in enumerate(factor_ids, 1):
            pool_stats = await FacFactorStats.filter(
                factor_id=factor_id,
                pool_id__in=pool_ids,
            )
            if not pool_stats:
                continue

            pool_grades = {s.pool_id: s.factor_grade for s in pool_stats if s.factor_grade}
            if not pool_grades:
                continue

            global_grade = grade_eval.calc_global_grade(pool_grades)

            await FacFactorRegistry.update_by(
                {"factor_grade": global_grade},
                factor_id=factor_id,
            )
            updated += 1
            if idx % 30 == 0 or idx == total:
                logger.info(
                    "[factor.evaluate] 全局等级更新进度: %d/%d (已更新=%d)",
                    idx, total, updated,
                )
