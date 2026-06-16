"""周频因子评估任务 — 按样本池计算 IC/ICIR/分层回测/换手率/衰减半衰期，评定因子等级。

评估流程（按因子滚动，参考业界主流因子评估平台架构）：
  1. 从 fac_factor_pool 读取样本池配置（含 factor_scope）
  2. 从 fac_factor_registry 读取活跃因子列表
  3. 逐样本池、逐因子加载截面面板 → 评估 → 即时持久化 → 释放内存
  4. 更新因子注册表的全局等级

按因子滚动的好处：
  - 内存峰值 = 1个因子 × 5年 × 样本池标的数，而非全量因子同时驻留
  - 每个因子评估完成即持久化，任务中断时已评估的结果不丢失
  - 进度可观测，每个因子完成时输出日志
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np

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

logger = get_logger("factor.evaluate")

_RETENTION_YEARS = 5
_DEFAULT_WINDOW = 252


class FactorEvaluateTask(BaseTask):
    """周频因子评估任务。"""

    task_name = "factor.evaluate_weekly"
    description = "按样本池计算因子统计指标并评定等级"
    prevent_concurrent = True

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        pool_ids = parse_list_param(kwargs.get("pool_ids"))
        factor_ids = parse_list_param(kwargs.get("factor_ids"))
        start_date = str(kwargs.get("start_date", ""))
        end_date = str(kwargs.get("end_date", ""))
        window = int(kwargs.get("window", _DEFAULT_WINDOW))

        # 从 DB 加载样本池配置（样本池数据由 SQL 脚本初始化，无需代码同步）
        if pool_ids:
            pools = await FacFactorPool.filter(
                pool_id__in=pool_ids,
                status="active",
            )
        else:
            pools = await FacFactorPool.filter(status="active")

        if not pools:
            return {"status": "FAILED", "message": "No active pools found"}

        # 解析全量活跃因子列表（排除收益率因子，收益率因子与 fwd_ret 列冲突且业务上不应评估）
        if factor_ids:
            factors = await FacFactorRegistry.filter(
                factor_id__in=factor_ids,
                status__in=["active", "testing"],
            )
        else:
            factors = await FacFactorRegistry.filter(
                status__in=["active", "testing"],
                category__ne="return",
            )

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
            "[factor.evaluate] starting | pools=%d factors=%d range=%s~%s window=%d",
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
                "[factor.evaluate] pool progress=%d/%d pool=%s factors=%d",
                pool_idx, total_pools, pool.pool_id, len(pool_factor_ids),
            )

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
            total_stats += count
            evaluated_pool_ids.append(pool.pool_id)

        # 更新因子注册表全局等级
        await self._update_global_grades(all_factor_ids, evaluated_pool_ids)

        logger.info(
            "[factor.evaluate] completed | total_stats=%d factors=%d pools=%s",
            total_stats, len(all_factor_ids), evaluated_pool_ids,
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
        """评估单个样本池的所有因子（按因子滚动：逐因子加载→评估→持久化→释放）。"""
        pool_id = pool.pool_id
        total_factors = len(factor_ids)
        logger.info("[factor.evaluate] 评估样本池: %s (%s), factors=%d", pool_id, pool.pool_name, total_factors)

        # 预加载样本池标的列表、行业映射和市值映射（所有因子共用）
        symbols = await reader.load_pool_symbols(pool_id)
        industry_map = await reader.load_industry_map(symbols)
        market_cap_map = await reader.load_market_cap_map(symbols)

        if not symbols:
            logger.warning("[factor.evaluate] 样本池 %s 无标的，跳过", pool_id)
            return 0

        # 预加载收益率面板（所有因子共用，按月滚动加载）
        returns_panel = await reader.load_returns_panel(
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
        )
        if returns_panel.empty:
            logger.warning("[factor.evaluate] 样本池 %s 收益率数据为空，跳过", pool_id)
            return 0

        # 逐因子滚动评估
        total_stats = 0
        today = date.today()

        for idx, factor_id in enumerate(factor_ids, 1):
            try:
                # 加载单因子截面面板（含截面预处理：缺失值填充→MAD→Z-score→行业+市值中性化→再Z-score）
                factor_panel = await reader.load_single_factor_panel(
                    start_date=start_date,
                    end_date=end_date,
                    pool_id=pool_id,
                    symbols=symbols,
                    factor_id=factor_id,
                    industry_map=industry_map,
                    market_cap_map=market_cap_map,
                )

                if factor_panel.empty or factor_id not in factor_panel.columns:
                    logger.debug("[factor.evaluate] 因子 %s 数据为空，跳过", factor_id)
                    continue

                single_factor = factor_panel[[factor_id]]

                # 计算统计指标
                stats = self._calc_factor_stats(
                    factor_id=factor_id,
                    factor_panel=single_factor,
                    returns_panel=returns_panel,
                    window=window,
                    ic_calc=ic_calc,
                    backtester=backtester,
                )

                stats["factor_id"] = factor_id
                stats["pool_id"] = pool_id
                stats["calc_date"] = today
                stats["window"] = window

                # 覆盖度
                total_cells = len(single_factor)
                non_null = single_factor[factor_id].notna().sum()
                stats["coverage"] = float(non_null / total_cells) if total_cells > 0 else 0.0

                # 评定等级
                grade = grade_eval.evaluate(stats)
                stats["factor_grade"] = grade

                # 即时持久化（单因子）
                model = self._build_stats_model(stats)
                await FacFactorStats.bulk_create_or_update(
                    [model],
                    on_conflict=None,
                )
                total_stats += 1

                logger.info(
                    "[factor.evaluate] pool=%s factor=%s (%d/%d) grade=%s icir=%.3f coverage=%.2f",
                    pool_id, factor_id, idx, total_factors, grade,
                    stats.get("icir", 0) or 0, stats.get("coverage", 0) or 0,
                )

            except Exception as e:
                logger.error("[factor.evaluate] 因子 %s 评估失败: %s", factor_id, e, exc_info=True)
                continue

        logger.info("[factor.evaluate] 样本池 %s: 评估完成, %d/%d 因子成功", pool_id, total_stats, total_factors)
        return total_stats

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
        ic_stats = ic_calc.calc_ic_stats(ic_series)

        # 分层回测
        backtest_result = backtester.run(factor_panel, returns_panel)

        # 换手率
        turnover = ic_calc.calc_turnover(factor_panel)

        # 衰减半衰期
        decay_half_life = ic_calc.calc_decay_half_life(factor_panel, returns_panel)

        return {
            "ic_mean": ic_stats.get("ic_mean"),
            "ic_std": ic_stats.get("ic_std"),
            "icir": ic_stats.get("icir"),
            "ic_win_rate": ic_stats.get("ic_win_rate"),
            "long_short_annual_ret": backtest_result.get("long_short_annual_ret"),
            "long_short_sharpe": backtest_result.get("long_short_sharpe"),
            "turnover": turnover,
            "decay_half_life": decay_half_life,
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
            turnover=_f(stats.get("turnover")),
            decay_half_life=_f(stats.get("decay_half_life")),
            long_short_annual_ret=_f(stats.get("long_short_annual_ret")),
            long_short_sharpe=_f(stats.get("long_short_sharpe")),
            coverage=_f(stats.get("coverage")),
            factor_grade=stats.get("factor_grade"),
        )

    @staticmethod
    async def _update_global_grades(factor_ids: list[str], pool_ids: list[str]) -> None:
        """更新因子注册表的全局等级（最优样本池规则）。"""
        grade_eval = GradeEvaluator()

        for factor_id in factor_ids:
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
            logger.debug(
                "[factor.evaluate] 因子 %s 全局等级更新为 %s (pool_grades=%s)",
                factor_id, global_grade, pool_grades,
            )
