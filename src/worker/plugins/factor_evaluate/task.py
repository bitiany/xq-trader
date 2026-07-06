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
import pandas as pd

from framework.commons.concurrent import ConcurrentRunner
from framework.commons.logger import get_logger
from framework.scheduler.base_task import BaseTask
from worker.plugins.utils import parse_list_param
from xqtrader.domain.factor.models.factor_pool import FacFactorPool
from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry
from xqtrader.domain.factor.models.factor_stats import FacFactorStats
from xqtrader.domain.factor.services import factor_data_loader as fdl
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
from xqtrader.domain.watermark.models.trade_calendar import TradeCalendar

logger = get_logger("factor.evaluate")

_RETENTION_YEARS = 5
# Forward-walk 多窗口并行评估：每个因子在每个样本池下产生 4 条 stats 记录
# - 63天（3月）: 短周期窗口，捕捉动量/技术/资金流因子的短期有效性
# - 126天（半年）: 中短周期窗口
# - 252天（1年）: 中长周期窗口，价值/质量因子开始稳定
# - 504天（2年）: 长周期窗口，长期稳定因子（价值/红利）的基准窗口
_EVAL_WINDOWS: tuple[int, ...] = (63, 126, 252, 504)
_DEFAULT_WINDOW = 504  # 兼容 plugin.yaml 入参（单窗口模式已废弃，仅在入参显式指定时使用）
# 评估任务消费者数量。
# 性能调优（2026-07-05）：
#   - 12 并发：DB 同时执行 12 个大批量 SELECT（每个 2000 symbols × 1210 天 = 2.4M rows），
#     磁盘 I/O 饱和，单批次查询从 110s 退化到 3320s（30 倍慢），1h45m 仅完成 30/132 因子
#   - 4 并发（旧方案，逐因子加载）：DB 同时执行 4 个 SELECT，单批次 110s，132 因子 3-4 小时
#   - 8 并发（新方案，预加载宽表）：computed 类因子已预加载到内存宽表，评估阶段为 CPU 密集型，
#     8 并发可充分利用 CPU；独立加载因子（fina_indicator 等）仍受 DB I/O 限制但数量少
#   - 连接池约束：stock 连接池 30，预加载阶段占用 1-5 连接（已释放），评估阶段 8 并发 + 独立加载 ≤ 12
_EVAL_CONCURRENCY = 8

# 不参与日频评估的因子类别：
# - return: 评估标签（fwd_ret_*），不评估
# - chanlun: 非截面连续值（缠论笔数等），覆盖率仅6%，IC异常，不入因子评估和合成
# - composite_group/composite_cross: 合成产物，不评估
# - interaction: 交互因子，合成产物，不评估
_EXCLUDED_CATEGORIES: tuple[str, ...] = (
    "return", "chanlun", "composite_group", "composite_cross", "interaction",
)

# 不参与日频评估的更新频率：
# - quarterly: 季频财务因子（B2-B5，32个）由 factor_evaluate_quarterly 任务独立评估，
#   避免在日频评估中因 PIT 前向填充导致评估结果失真
_EXCLUDED_UPDATE_FREQS: tuple[str, ...] = ("quarterly",)

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
    pool_start_time: float  # 池评估启动时间（time.monotonic），用于单因子日志输出累计耗时
    factor_raw_panels: dict[str, Any] | None  # 预加载的因子原始面板（None 表示未预加载，回退到逐因子加载）


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

        # 清空空池缓存（防止上次任务的缓存残留）
        fdl.clear_empty_pool_cache()

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
        # 排除：quarterly(季频财务因子) — 由 factor_evaluate_quarterly 任务独立评估
        excluded_set = set(_EXCLUDED_CATEGORIES)
        excluded_freq_set = set(_EXCLUDED_UPDATE_FREQS)
        if factor_ids:
            all_factors = await FacFactorRegistry.filter(
                factor_id__in=factor_ids,
                status="active",
            )
        else:
            all_factors = await FacFactorRegistry.filter(status="active")
        factors = [
            f for f in all_factors
            if f.category not in excluded_set
            and (f.update_freq or "daily") not in excluded_freq_set
        ]

        if not factors:
            return {"status": "FAILED", "message": "No active factors to evaluate"}

        all_factor_ids = [f.factor_id for f in factors]

        # 计算日期范围：以最新交易日作为评估日（calc_date），避免跨 UTC 0 点导致非交易日写入
        # 周频长跑任务可能跨越 UTC 0 点，date.today() 会变成非交易日（如周六），
        # 导致同一次评估产生两个 calc_date，破坏周频评估日期一致性。
        ref_trade_date = await TradeCalendar.get_latest_trade_date()
        if ref_trade_date is None:
            # 交易日历缺失时回退到 today（仅作兜底，正常情况不会触发）
            logger.warning("[factor.evaluate] 交易日历查询失败，回退使用 date.today()")
            ref_trade_date = date.today()

        if not end_date:
            end_date = ref_trade_date.strftime("%Y-%m-%d")
        if not start_date:
            start = ref_trade_date - timedelta(days=_RETENTION_YEARS * 365)
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
                "[factor.evaluate] >>> 池进度 %d/%d pool=%s factors=%d (累计耗时=%.1fs)",
                pool_idx, total_pools, pool.pool_id, len(pool_factor_ids),
                time.monotonic() - task_start_time,
            )

            pool_start = time.monotonic()
            count = await self._evaluate_pool(
                pool=pool,
                factor_ids=pool_factor_ids,
                start_date=start_dt,
                end_date=end_dt,
                window=window,
                today=ref_trade_date,
                reader=reader,
                ic_calc=ic_calc,
                backtester=backtester,
                grade_eval=grade_eval,
            )
            pool_elapsed = time.monotonic() - pool_start
            total_stats += count
            evaluated_pool_ids.append(pool.pool_id)

            # 基于已完成池的平均耗时预估剩余
            avg_pool_time = (time.monotonic() - task_start_time) / pool_idx
            remaining_pools = total_pools - pool_idx
            eta_seconds = avg_pool_time * remaining_pools
            logger.info(
                "[factor.evaluate] <<< 池完成 %d/%d pool=%s 成功=%d/%d 耗时=%.1fs "
                "累计stats=%d 累计耗时=%.1fs 剩余%d池 预估ETA=%.0f分钟",
                pool_idx, total_pools, pool.pool_id, count, len(pool_factor_ids),
                pool_elapsed, total_stats, time.monotonic() - task_start_time,
                remaining_pools, eta_seconds / 60.0,
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
        today: date,
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

        Args:
            today: 评估日（calc_date），由调用方统一传入最新交易日，
                   避免跨池跨 UTC 0 点导致 calc_date 不一致
        """
        pool_id = pool.pool_id
        total_factors = len(factor_ids)
        pool_t0 = time.monotonic()
        logger.info(
            "[factor.evaluate] >>> 进入样本池: %s (%s) factors=%d concurrency=%d",
            pool_id, pool.pool_name, total_factors, _EVAL_CONCURRENCY,
        )

        # 预探测 pool_id 在 fac_factor_value 中是否有数据
        # 风格池（style_value/style_growth 等）在 fac_factor_value 中无数据，
        # 探测一次后加入空池缓存，后续所有因子直接查 all 池，避免 100-190s/因子的空查询
        t0 = time.monotonic()
        has_factor_data = await fdl.probe_pool_has_factor_data(pool_id)
        logger.info(
            "[factor.evaluate] pool=%s 因子数据探测: has_factor_data=%s 耗时=%.2fs",
            pool_id, has_factor_data, time.monotonic() - t0,
        )
        if not has_factor_data:
            logger.info(
                "[factor.evaluate] pool=%s 在 fac_factor_value 中无数据,"
                "所有因子将直接使用 all 池（symbol 已按样本池过滤）",
                pool_id,
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

        # 预加载因子原始面板宽表（消除 computed 类因子的重复 DB 查询）
        # computed/fund_flow/market/derived 类因子（约 114 个）通过一次 DB 查询批量加载，
        # 评估阶段从内存宽表切片，CPU 密集型可支持 8 并发；其他类因子保持独立加载
        t0 = time.monotonic()
        factor_raw_panels = await fdl.preload_factor_raw_panels(
            start_date=start_date,
            end_date=end_date,
            factor_ids=factor_ids,
            symbols=symbols,
            pool_id=pool_id,
        )
        logger.info(
            "[factor.evaluate] pool=%s 因子原始面板预加载: %d/%d 耗时=%.2fs",
            pool_id, len(factor_raw_panels), len(factor_ids), time.monotonic() - t0,
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
            today=today,
            pool_start_time=pool_t0,
            factor_raw_panels=factor_raw_panels,
        )

        # 生产者-消费者并发评估
        runner = ConcurrentRunner[str, dict](
            concurrency=_EVAL_CONCURRENCY,
            log_name=f"factor.evaluate[{pool_id}]",
        )
        eval_t0 = time.monotonic()
        result = await runner.run_items(
            items=factor_ids,
            processor=lambda fid: self._evaluate_single_factor(fid, ctx),
        )
        eval_elapsed = time.monotonic() - eval_t0

        # 估算剩余时间（基于已评估因子平均耗时）
        avg_per_factor = eval_elapsed / total_factors if total_factors > 0 else 0.0
        logger.info(
            "[factor.evaluate] <<< 样本池 %s 评估完成: 成功=%d/%d 失败=%d "
            "并发评估=%.1fs (平均%.1fs/因子) 预加载=%.1fs 池总耗时=%.1fs",
            pool_id, result.success_count, total_factors,
            result.failure_count, eval_elapsed, avg_per_factor,
            eval_t0 - pool_t0, time.monotonic() - pool_t0,
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
        pool_elapsed = time.monotonic() - ctx.pool_start_time
        logger.info(
            "[factor.evaluate] pool=%s >>> 开始评估 factor=%s (池累计=%.1fs)",
            ctx.pool_id, factor_id, pool_elapsed,
        )

        # 加载单因子截面面板（含截面预处理：缺失值填充→MAD→Z-score→行业+市值中性化→再Z-score）
        # 因子级 start_date：受数据源限制的因子（如 fund_flow 自 2023-09-11 起）使用自身起始日期，
        # 避免在 5 年默认窗口中因覆盖率不足 80% 被门禁拦截
        factor_data_start = ctx.data_start_map.get(factor_id)
        effective_start = max(ctx.start_date, factor_data_start) if factor_data_start else ctx.start_date

        t0 = time.monotonic()
        # 优先从预加载宽表切片（消除 computed 类因子的 DB I/O 瓶颈），
        # 未命中（fina_indicator/daily_indicator/cross_section_* 等独立加载因子）时回退到逐因子加载
        if ctx.factor_raw_panels is not None and factor_id in ctx.factor_raw_panels:
            raw_panel = ctx.factor_raw_panels[factor_id]
            # 按 effective_start 过滤（因子级 start_date，避免数据源限制因子被门禁拦截）
            # trade_date 可能是 date 对象或 Timestamp，统一用 pd.to_datetime 转换后比较
            if factor_data_start and effective_start > ctx.start_date:
                td_index = pd.to_datetime(raw_panel.index.get_level_values("trade_date"))
                mask = td_index >= pd.Timestamp(effective_start)
                raw_panel = raw_panel[mask]
            factor_panel = reader.process_preloaded_factor_panel(
                factor_df=raw_panel,
                pool_id=ctx.pool_id,
                factor_id=factor_id,
                industry_map=ctx.industry_map,
                market_cap_panel=ctx.market_cap_panel,
            )
        else:
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

        # === 预计算阶段：不依赖 window 的全量指标（窗口循环外，仅计算 1 次） ===
        # 性能优化（2026-07-04）：
        #   优化前：calc_ic_series(1d) + calc_ic_series_multi_horizon(5/10/20d) 共 4 次遍历 dates，
        #           每次调用 spearmanr（含内部 rank），1210 日期 × 4 = 4840 次 spearmanr。
        #   优化后：calc_all_ic_series 一次遍历，预计算每个日期的因子 rank（多 horizon 共用），
        #           用 numpy Pearson 替代 scipy spearmanr，预计提速 5-10 倍。
        t_pre = time.monotonic()
        all_ic_series = ctx.ic_calc.calc_all_ic_series(
            single_factor, ctx.returns_panel, horizons=(1, 5, 10, 20),
        )
        ic_series_1d = all_ic_series.get(1, pd.Series(dtype=float, name="ic_1d"))
        multi_ic_series = {
            h: all_ic_series[h] for h in (5, 10, 20) if h in all_ic_series
        }
        turnover = ctx.ic_calc.calc_turnover(single_factor)
        ic_decay_curve, decay_half_life = ctx.ic_calc.calc_decay_info(
            single_factor, ctx.returns_panel,
        )
        pre_elapsed = time.monotonic() - t_pre
        logger.info(
            "[factor.evaluate] pool=%s factor=%s 预计算完成: ic_1d_n=%d multi_horizons=%d "
            "turnover=%.4f decay_half_life=%s 耗时=%.2fs",
            ctx.pool_id, factor_id, len(ic_series_1d), len(multi_ic_series),
            turnover or 0.0, decay_half_life, pre_elapsed,
        )

        # === 窗口循环：仅做依赖 window 的截取计算 ===
        t_win = time.monotonic()
        window_results: list[dict[str, Any]] = []
        for win in _EVAL_WINDOWS:
            stats = self._calc_window_stats(
                window=win,
                ic_series_1d=ic_series_1d,
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
            stats["window"] = win
            stats["coverage"] = coverage  # 复用门禁检查中已计算的覆盖度

            # 评定等级（每个窗口独立评级）
            grade = ctx.grade_eval.evaluate(stats)
            stats["factor_grade"] = grade
            window_results.append(stats)

        logger.info(
            "[factor.evaluate] pool=%s factor=%s 多窗口 stats 计算完成 windows=%d 耗时=%.2fs",
            ctx.pool_id, factor_id, len(window_results), time.monotonic() - t_win,
        )

        # 即时持久化（单因子多窗口批量写入）
        t_persist = time.monotonic()
        models = [self._build_stats_model(s) for s in window_results]
        await FacFactorStats.bulk_create_or_update(
            models,
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

        # 取长周期窗口（504天）作为日志输出的代表等级
        primary_stats = next((s for s in window_results if s["window"] == 504), window_results[0])
        logger.info(
            "[factor.evaluate] pool=%s factor=%s <<< 评估完成 windows=%d grades=%s "
            "icir_504=%.3f coverage=%.2f 预计算=%.2fs 窗口计算=%.2fs 持久化=%.2fs 总耗时=%.2fs 池累计=%.1fs",
            ctx.pool_id, factor_id, len(window_results),
            {s["window"]: s["factor_grade"] for s in window_results},
            primary_stats.get("icir", 0) or 0, primary_stats.get("coverage", 0) or 0,
            pre_elapsed, time.monotonic() - t_win, time.monotonic() - t_persist,
            time.monotonic() - factor_t0, time.monotonic() - ctx.pool_start_time,
        )
        return primary_stats

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
    def _calc_window_stats(
        window: int,
        ic_series_1d: Any,
        multi_ic_series: dict[int, Any],
        factor_panel: Any,
        returns_panel: Any,
        turnover: float | None,
        ic_decay_curve: list[dict[str, Any]],
        decay_half_life: float | None,
        ic_calc: ICCalculator,
        backtester: LayeredBacktester,
    ) -> dict[str, Any]:
        """计算单个窗口的 stats（基于预计算的全量指标按 window 截取）。

        Forward-walk 优化：不依赖 window 的指标（IC 序列/换手率/衰减）已在窗口循环外
        预计算完成，本方法只做依赖 window 的截取计算（ic_stats/ic_sig/multi_ic_stats/backtest）。

        Args:
            window: forward-walk 窗口天数
            ic_series_1d: 预计算的全量 1d IC 序列
            multi_ic_series: 预计算的多 horizon 全量 IC 序列 {horizon: ic_series}
            factor_panel: 单因子截面面板（已应用方向翻转）
            returns_panel: 收益率面板
            turnover: 预计算的换手率
            ic_decay_curve: 预计算的 IC 衰减曲线
            decay_half_life: 预计算的半衰期
            ic_calc: ICCalculator 实例
            backtester: LayeredBacktester 实例

        Returns:
            该窗口的统计指标字典
        """
        # IC 截面统计（按末 window 日截取 IC 序列）
        ic_stats = ic_calc.calc_ic_stats(ic_series_1d, window=window)
        ic_sig = ic_calc.calc_ic_significance(ic_series_1d, window=window)
        multi_ic = ic_calc.calc_multi_horizon_ic_stats(multi_ic_series, window=window)

        # 分层回测（forward-walk 窗口截取）
        backtest_result = backtester.run(factor_panel, returns_panel, window=window)

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
        """更新因子注册表的全局等级（多窗口×多池最优规则）。

        多窗口评估下，每个因子有 4 窗口 × 8 池 = 32 条 stats 记录。
        全局等级取所有窗口×所有池的最高等级，捕捉因子在不同周期下的最优表现。
        """
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

            # 多窗口×多池：所有 stats 的等级合并计算，取最高等级
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
