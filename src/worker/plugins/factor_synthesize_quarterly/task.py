"""季频 Alpha 合成任务 — 按样本池对季频财务因子截面标准化后合成 Alpha 因子。

与日频合成（factor.synthesize_weekly）的区别：
  - 输入因子：update_freq=quarterly 的财务因子（B2-B5，32 个）
  - 合成锚点：ann_date（公告日，PIT 依据），非 trade_date
  - 持久化表：fac_financial_composite_value，非 fac_factor_value
  - ICIR 来源：fac_financial_factor_stats（ann_window=20），非滚动 IC 计算

合成流程（两阶段分层合成）：
  1. 从 fac_financial_factor_stats 读取 A/B 级季频因子（按样本池维度）
  2. 逐样本池：
     a. 加载 PIT 财务因子面板（前向填充到日频）+ 截面预处理
     b. 第一阶段：组内等权合成 → 4 个组内合成因子
     c. 第二阶段：跨组 ICIR 加权合成 → composite_alpha_quarterly
     d. 按 ann_date 持久化到 fac_financial_composite_value
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from framework.commons.concurrent import ConcurrentRunner
from framework.commons.logger import get_logger
from framework.scheduler.base_task import BaseTask
from worker.plugins.factor_synthesize_quarterly.factors import (
    CompositeAlphaQuarterlyFactor,
    CompositeEfficiencyQuarterlyFactor,
    CompositeGrowthQuarterlyFactor,
    CompositeLeverageQuarterlyFactor,
    CompositeQualityQuarterlyFactor,
)
from worker.plugins.utils import parse_list_param
from xqtrader.domain.factor.models.factor_pool import FacFactorPool
from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry
from xqtrader.domain.factor.models.financial_composite_value import (
    FacFinancialCompositeValue,
)
from xqtrader.domain.factor.models.financial_factor_stats import (
    FacFinancialFactorStats,
)
from xqtrader.domain.factor.models.financial_factor_value import (
    FacFinancialFactorValue,
)
from xqtrader.domain.factor.services.cross_section_reader import CrossSectionReader
from xqtrader.domain.factor.services.factor_data_loader import load_financial_pit_panel
from xqtrader.domain.factor.services.pool_init import PoolInitService
from xqtrader.domain.factor.services.registry import (
    auto_discover_factors,
    register_factor_variants,
)
from xqtrader.domain.watermark.models.trade_calendar import TradeCalendar

logger = get_logger("factor.synthesize_quarterly")

_RETENTION_YEARS = 7  # 季频合成需要更长历史（7 年 ≈ 28 季度）
# 从 fac_financial_factor_stats 读取 ICIR 的评估窗口（20Q 长周期窗口，统计稳定性最高）
_DEFAULT_ANN_WINDOW = 20
_PERSIST_BATCH_SIZE = 5000
_SYNTH_CONCURRENCY = 4  # 持久化消费者数量

# 季频合成因子分组配置（与 factors.py 定义保持一致）
_GROUP_COMPOSITE_MAP: dict[str, tuple[str, list[str]]] = {
    "quality": (
        "composite_quality_quarterly",
        CompositeQualityQuarterlyFactor.composite_factor_ids,
    ),
    "growth": (
        "composite_growth_quarterly",
        CompositeGrowthQuarterlyFactor.composite_factor_ids,
    ),
    "leverage": (
        "composite_leverage_quarterly",
        CompositeLeverageQuarterlyFactor.composite_factor_ids,
    ),
    "efficiency": (
        "composite_efficiency_quarterly",
        CompositeEfficiencyQuarterlyFactor.composite_factor_ids,
    ),
}
_CROSS_COMPOSITE_FACTOR_ID = CompositeAlphaQuarterlyFactor.factor_id


class FactorSynthesizeQuarterlyTask(BaseTask):
    """季频 Alpha 合成任务。"""

    task_name = "factor.synthesize_quarterly"
    description = "按样本池对季频财务因子截面标准化后合成Alpha因子(组内等权+跨组ICIR加权)"
    prevent_concurrent = True

    async def _run_impl(self, **kwargs: Any) -> dict[str, Any]:
        task_start_time = time.monotonic()
        pool_ids = parse_list_param(kwargs.get("pool_ids"))
        factor_ids = parse_list_param(kwargs.get("factor_ids"))
        start_date = str(kwargs.get("start_date", ""))
        end_date = str(kwargs.get("end_date", ""))
        ann_window = int(kwargs.get("ann_window", _DEFAULT_ANN_WINDOW))

        logger.info(
            "[factor.synth_q] === 任务启动 === params: pool_ids=%s factor_ids=%s ann_window=%d",
            pool_ids, factor_ids, ann_window,
        )

        # 同步默认样本池配置 + 注册季频合成因子
        await PoolInitService().sync_default_pools()
        auto_discover_factors()
        register_factor_variants()

        # 从 DB 加载样本池
        if pool_ids:
            pools = await FacFactorPool.filter(
                pool_id__in=pool_ids, status="active",
            )
        else:
            pools = await FacFactorPool.filter(status="active")
        if not pools:
            return {"status": "FAILED", "message": "No active pools found"}

        # 计算日期范围：以最新交易日作为评估日
        ref_trade_date = await TradeCalendar.get_latest_trade_date()
        if ref_trade_date is None:
            logger.warning("[factor.synth_q] 交易日历查询失败，回退使用 date.today()")
            ref_trade_date = date.today()

        if not end_date:
            end_date = ref_trade_date.strftime("%Y-%m-%d")
        if not start_date:
            start = ref_trade_date - timedelta(days=_RETENTION_YEARS * 365)
            start_date = start.strftime("%Y-%m-%d")

        start_dt = date.fromisoformat(start_date)
        end_dt = date.fromisoformat(end_date)

        logger.info(
            "[factor.synth_q] === 开始季频合成 === pools=%d range=%s~%s",
            len(pools), start_date, end_date,
        )

        total_upserted = 0
        synthesized_pools: list[str] = []
        for pool_idx, pool in enumerate(pools, 1):
            pool_factor_ids = factor_ids or await self._resolve_pool_factors(
                pool.pool_id, ann_window,
            )
            if not pool_factor_ids:
                logger.warning(
                    "[factor.synth_q] pool=%s 无可用因子，跳过", pool.pool_id,
                )
                continue

            logger.info(
                "[factor.synth_q] >>> 池进度 %d/%d pool=%s factors=%d (累计耗时=%.1fs)",
                pool_idx, len(pools), pool.pool_id, len(pool_factor_ids),
                time.monotonic() - task_start_time,
            )

            try:
                results = await self._synthesize_pool(
                    pool_id=pool.pool_id,
                    factor_ids=pool_factor_ids,
                    start_date=start_dt,
                    end_date=end_dt,
                    ann_window=ann_window,
                )
            except Exception as e:
                logger.error(
                    "[factor.synth_q] pool=%s 合成失败: %s", pool.pool_id, e, exc_info=True,
                )
                continue

            if not results:
                continue

            count = await self._persist_results(
                pool_id=pool.pool_id,
                factor_ids=pool_factor_ids,
                start_date=start_dt,
                end_date=end_dt,
                results=results,
            )
            total_upserted += count
            synthesized_pools.append(pool.pool_id)

            logger.info(
                "[factor.synth_q] pool=%s 完成: upserted=%d composites=%s",
                pool.pool_id, count, list(results.keys()),
            )

        logger.info(
            "[factor.synth_q] === 任务完成 === pools=%s total_upserted=%d 总耗时=%.1fs",
            synthesized_pools, total_upserted, time.monotonic() - task_start_time,
        )
        return {
            "status": "SUCCESS",
            "total_upserted": total_upserted,
            "pools": synthesized_pools,
        }

    @staticmethod
    async def _resolve_pool_factors(
        pool_id: str, ann_window: int,
    ) -> list[str]:
        """解析样本池内 A/B 级季频因子列表（按指定评估窗口筛选）。

        优先级：
          1. 指定窗口的 A/B 级因子（从 fac_financial_factor_stats）
          2. 全部活跃 quarterly 因子（兜底）
        """
        stats = await FacFinancialFactorStats.filter(
            pool_id=pool_id,
            ann_window=ann_window,
            factor_grade__in=["A", "B"],
        )
        if stats:
            factor_ids = sorted({s.factor_id for s in stats})
            logger.info(
                "[factor.synth_q] pool=%s window=%dQ 从 stats 读取 A/B 级因子: %d",
                pool_id, ann_window, len(factor_ids),
            )
            return factor_ids

        # 兜底：全部活跃 quarterly 因子
        registry = await FacFactorRegistry.filter(
            status="active", update_freq="quarterly",
        )
        factor_ids = sorted(f.factor_id for f in registry)
        logger.info(
            "[factor.synth_q] pool=%s window=%dQ 无 A/B 级因子，使用全部活跃季频因子: %d",
            pool_id, ann_window, len(factor_ids),
        )
        return factor_ids

    async def _synthesize_pool(
        self,
        pool_id: str,
        factor_ids: list[str],
        start_date: date,
        end_date: date,
        ann_window: int,
    ) -> dict[str, pd.DataFrame]:
        """合成单个样本池的季频合成因子。

        两阶段合成：
          1. 组内等权合成 → 4 个组内合成因子
          2. 跨组 ICIR 加权合成 → composite_alpha_quarterly

        Returns:
            {composite_factor_id: DataFrame(MultiIndex: trade_date, symbol)}
        """
        reader = CrossSectionReader()

        # 加载样本池标的 + 行业映射 + 市值面板
        symbols = await reader.load_pool_symbols(pool_id)
        if not symbols:
            logger.warning("[factor.synth_q] 样本池 %s 无标的，跳过", pool_id)
            return {}

        industry_map = await reader.load_industry_map(symbols)
        market_cap_panel = await reader.load_market_cap_panel(symbols, start_date, end_date)

        # 加载并预处理各因子面板
        factor_panels = await self._load_factor_panels(
            reader=reader,
            pool_id=pool_id,
            factor_ids=factor_ids,
            symbols=symbols,
            industry_map=industry_map,
            market_cap_panel=market_cap_panel,
            start_date=start_date,
            end_date=end_date,
        )
        if len(factor_panels) < 2:
            logger.warning(
                "[factor.synth_q] pool=%s 有效因子不足 2 个(%d)，跳过",
                pool_id, len(factor_panels),
            )
            return {}

        # 合并为宽表
        combined = pd.DataFrame(factor_panels)
        logger.info(
            "[factor.synth_q] pool=%s 因子面板合并完成: rows=%d factors=%d",
            pool_id, len(combined), len(combined.columns),
        )

        # 第一阶段：组内等权合成
        group_alphas = self._synthesize_within_groups(combined, pool_id)
        if not group_alphas:
            logger.warning("[factor.synth_q] pool=%s 组内合成无结果，跳过", pool_id)
            return {}

        # 第二阶段：跨组 ICIR 加权合成
        group_icir_weights = await self._load_group_icir_weights(
            pool_id, ann_window, factor_ids,
        )
        alpha_panel = self._synthesize_cross_group(
            group_alphas, group_icir_weights, pool_id,
        )

        results: dict[str, pd.DataFrame] = {}
        for composite_fid, group_series in group_alphas.items():
            results[composite_fid] = group_series.to_frame(composite_fid)
        if not alpha_panel.empty:
            results[_CROSS_COMPOSITE_FACTOR_ID] = alpha_panel

        for composite_fid, df in results.items():
            logger.info(
                "[factor.synth_q] pool=%s composite=%s rows=%d non_nan=%d",
                pool_id, composite_fid, len(df), int(df.iloc[:, 0].notna().sum()),
            )
        return results

    @staticmethod
    async def _load_factor_panels(
        reader: CrossSectionReader,
        pool_id: str,
        factor_ids: list[str],
        symbols: list[str],
        industry_map: dict[str, Any],
        market_cap_panel: Any,
        start_date: date,
        end_date: date,
    ) -> dict[str, pd.Series]:
        """加载并截面预处理各因子面板，返回 {factor_id: Series(MultiIndex)}。"""
        # 加载因子方向
        regs = await FacFactorRegistry.filter(factor_id__in=factor_ids)
        direction_map = {r.factor_id: (r.direction or "DESC") for r in regs}

        factor_panels: dict[str, pd.Series] = {}
        for fid in factor_ids:
            t0 = time.monotonic()
            # 加载 PIT 财务因子面板（前向填充到日频）
            raw_panel = await load_financial_pit_panel(start_date, end_date, fid, symbols)
            if raw_panel.empty or fid not in raw_panel.columns:
                logger.info(
                    "[factor.synth_q] pool=%s factor=%s 数据为空，跳过 耗时=%.2fs",
                    pool_id, fid, time.monotonic() - t0,
                )
                continue

            # 截面预处理（缺失值填充→MAD→Z-score→行业+市值中性化→再Z-score）
            processed = reader.process_preloaded_factor_panel(
                factor_df=raw_panel,
                pool_id=pool_id,
                factor_id=fid,
                industry_map=industry_map,
                market_cap_panel=market_cap_panel,
            )
            if processed.empty or fid not in processed.columns:
                logger.info(
                    "[factor.synth_q] pool=%s factor=%s 预处理后为空，跳过",
                    pool_id, fid,
                )
                continue

            series = processed[fid]
            # 应用因子方向（ASC 取反）
            if direction_map.get(fid, "DESC") == "ASC":
                series = -series
            factor_panels[fid] = series

            logger.info(
                "[factor.synth_q] pool=%s factor=%s 面板加载+预处理完成: rows=%d 耗时=%.2fs",
                pool_id, fid, len(series), time.monotonic() - t0,
            )
        return factor_panels

    @staticmethod
    def _synthesize_within_groups(
        combined: pd.DataFrame,
        pool_id: str,
    ) -> dict[str, pd.Series]:
        """第一阶段：组内等权合成。

        按 _GROUP_COMPOSITE_MAP 配置，对每组内的因子等权平均，
        产出 4 个组内合成因子。
        """
        group_alphas: dict[str, pd.Series] = {}
        for group_name, (composite_fid, member_ids) in _GROUP_COMPOSITE_MAP.items():
            available = [fid for fid in member_ids if fid in combined.columns]
            if not available:
                logger.warning(
                    "[factor.synth_q] pool=%s 组=%s 无可用因子，跳过 (声明 %d, 实际 %d)",
                    pool_id, group_name, len(member_ids), len(available),
                )
                continue
            group_alpha = combined[available].mean(axis=1)
            group_alphas[composite_fid] = group_alpha
            logger.info(
                "[factor.synth_q] pool=%s 组内合成: composite=%s factors=%d/%d",
                pool_id, composite_fid, len(available), len(member_ids),
            )
        return group_alphas

    @staticmethod
    async def _load_group_icir_weights(
        pool_id: str,
        ann_window: int,
        input_factor_ids: list[str],
    ) -> dict[str, float]:
        """从 fac_financial_factor_stats 加载各组的 ICIR 权重。

        每组的 ICIR = 组内成员因子 ICIR 绝对值的均值。
        无 ICIR 数据时返回空 dict（跨组加权退化为等权）。
        """
        stats = await FacFinancialFactorStats.filter(
            pool_id=pool_id,
            ann_window=ann_window,
            factor_id__in=input_factor_ids,
        )
        icir_map = {s.factor_id: float(s.icir or 0.0) for s in stats}

        group_weights: dict[str, float] = {}
        for group_name, (_composite_fid, member_ids) in _GROUP_COMPOSITE_MAP.items():
            member_icirs = [abs(icir_map[fid]) for fid in member_ids if fid in icir_map]
            if not member_icirs:
                continue
            group_weights[group_name] = float(np.mean(member_icirs))

        if not group_weights:
            logger.warning(
                "[factor.synth_q] pool=%s window=%dQ 无 ICIR 数据，跨组加权退化为等权",
                pool_id, ann_window,
            )
            return {}

        logger.info(
            "[factor.synth_q] pool=%s window=%dQ 组 ICIR 权重: %s",
            pool_id, ann_window, {k: round(v, 4) for k, v in group_weights.items()},
        )
        return group_weights

    @staticmethod
    def _synthesize_cross_group(
        group_alphas: dict[str, pd.Series],
        group_weights: dict[str, float],
        pool_id: str,
    ) -> pd.DataFrame:
        """第二阶段：跨组 ICIR 加权合成 composite_alpha_quarterly。

        无权重时退化为等权合成。
        """
        if not group_alphas:
            return pd.DataFrame()

        group_combined = pd.DataFrame(group_alphas)

        # 反向映射 composite_fid → group_name
        fid_to_group = {
            composite_fid: group_name
            for group_name, (composite_fid, _member_ids) in _GROUP_COMPOSITE_MAP.items()
        }

        # 构建权重 Series（按 group_combined 的列顺序对齐）
        if group_weights:
            weights = {
                composite_fid: group_weights.get(fid_to_group.get(composite_fid, ""), 0.0)
                for composite_fid in group_combined.columns
            }
            # 全部权重为 0 时退化为等权
            if sum(weights.values()) == 0:
                logger.warning(
                    "[factor.synth_q] pool=%s 所有组权重为 0，退化为等权", pool_id,
                )
                result = group_combined.mean(axis=1).to_frame(_CROSS_COMPOSITE_FACTOR_ID)
                return result

            weight_series = pd.Series(weights)
            weight_series = weight_series / weight_series.sum()
            # 按列加权求和
            weighted = group_combined.multiply(weight_series, axis=1).sum(axis=1)
            result = weighted.to_frame(_CROSS_COMPOSITE_FACTOR_ID)
        else:
            result = group_combined.mean(axis=1).to_frame(_CROSS_COMPOSITE_FACTOR_ID)

        logger.info(
            "[factor.synth_q] pool=%s 跨组合成完成: rows=%d",
            pool_id, len(result),
        )
        return result

    async def _persist_results(
        self,
        pool_id: str,
        factor_ids: list[str],
        start_date: date,
        end_date: date,
        results: dict[str, pd.DataFrame],
    ) -> int:
        """将合成结果按 ann_date 持久化到 fac_financial_composite_value。

        持久化策略：仅在输入因子的 ann_date 上存储合成因子值，
        避免按全部交易日存储导致的冗余（28 季度 × 5294 标的 × 5 合成因子 ≈ 0.74M rows）。
        """
        # 加载 (symbol, ann_date) 索引：输入因子的实际公告日
        ann_date_index = await self._load_ann_date_index(factor_ids, start_date, end_date)
        if not ann_date_index:
            logger.warning(
                "[factor.synth_q] pool=%s 无 ann_date 索引，跳过持久化", pool_id,
            )
            return 0

        # 按合成因子并发持久化
        items: list[tuple[str, pd.DataFrame]] = [
            (composite_fid, df) for composite_fid, df in results.items() if not df.empty
        ]
        if not items:
            return 0

        runner = ConcurrentRunner[tuple[str, pd.DataFrame], int](
            concurrency=_SYNTH_CONCURRENCY,
            log_name=f"factor.synth_q.persist[{pool_id}]",
        )
        result = await runner.run_items(
            items=items,
            processor=lambda item: self._persist_single_composite(
                pool_id, item[0], item[1], ann_date_index,
            ),
        )
        return sum(result.succeeded)

    @staticmethod
    async def _load_ann_date_index(
        factor_ids: list[str],
        start_date: date,
        end_date: date,
    ) -> dict[str, set[date]]:
        """加载输入因子的 (symbol, ann_date) 索引。

        Returns:
            {symbol: set(ann_date)}  每个标的的公告日集合
        """
        records = await FacFinancialFactorValue.filter(
            factor_id__in=factor_ids,
            ann_date__gte=start_date,
            ann_date__lte=end_date,
        )

        index: dict[str, set[date]] = {}
        for r in records:
            sym = r.symbol
            ad = r.ann_date
            if hasattr(ad, "isoformat"):
                ad = date.fromisoformat(ad.isoformat()[:10])
            index.setdefault(sym, set()).add(ad)

        total_pairs = sum(len(dates) for dates in index.values())
        logger.info(
            "[factor.synth_q] ann_date 索引加载: symbols=%d total_pairs=%d",
            len(index), total_pairs,
        )
        return index

    @staticmethod
    async def _persist_single_composite(
        pool_id: str,
        composite_fid: str,
        df: pd.DataFrame,
        ann_date_index: dict[str, set[date]],
    ) -> int:
        """持久化单个合成因子（按 ann_date 索引过滤后分片 upsert）。

        使用集合查找过滤 (symbol, ann_date) 在索引中的行，避免 iterrows 性能损耗。
        """
        if df.empty:
            return 0

        col = df.columns[0]
        # 还原 MultiIndex 为列
        reset_df = df.reset_index()
        td_col = "trade_date" if "trade_date" in reset_df.columns else reset_df.columns[0]
        sym_col = "symbol" if "symbol" in reset_df.columns else reset_df.columns[1]

        # 统一 trade_date 为 date 对象
        td_series = reset_df[td_col]
        if pd.api.types.is_datetime64_any_dtype(td_series):
            td_dates = td_series.dt.date.tolist()
        else:
            td_dates = [
                d.date() if hasattr(d, "date") else d
                for d in td_series.tolist()
            ]

        # 过滤：(symbol, trade_date) 在 ann_date_index 中
        sym_list = reset_df[sym_col].astype(str).tolist()
        keep_idx: list[int] = []
        for i, (sym, td) in enumerate(zip(sym_list, td_dates)):
            ann_dates = ann_date_index.get(sym)
            if ann_dates is not None and td in ann_dates:
                keep_idx.append(i)

        if not keep_idx:
            return 0

        keep_df = reset_df.iloc[keep_idx].reset_index(drop=True)
        vals = keep_df[col].to_numpy(dtype=float)
        valid_mask = np.isfinite(vals)
        if not valid_mask.any():
            return 0

        keep_df = keep_df.loc[valid_mask].reset_index(drop=True)
        vals = vals[valid_mask]
        keep_td = [td_dates[i] for i in keep_idx]
        keep_td = [
            keep_td[i] for i in range(len(keep_td)) if valid_mask[i]
        ]
        keep_sym = [sym_list[i] for i in keep_idx]
        keep_sym = [
            keep_sym[i] for i in range(len(keep_sym)) if valid_mask[i]
        ]
        n = len(keep_df)
        total = 0

        for start in range(0, n, _PERSIST_BATCH_SIZE):
            end = min(start + _PERSIST_BATCH_SIZE, n)
            rows: list[FacFinancialCompositeValue] = []
            for idx in range(start, end):
                rows.append(FacFinancialCompositeValue(
                    symbol=str(keep_sym[idx]),
                    ann_date=keep_td[idx],
                    factor_id=composite_fid,
                    pool_id=pool_id,
                    factor_value=float(vals[idx]),
                ))

            total += await FacFinancialCompositeValue.bulk_create_or_update(
                rows,
                on_conflict=["symbol", "ann_date", "factor_id", "pool_id"],
                update_fields=["factor_value"],
            )
            if end == n or end % (_PERSIST_BATCH_SIZE * 10) == 0:
                logger.info(
                    "[factor.synth_q] pool=%s composite=%s persist progress=%d/%d",
                    pool_id, composite_fid, end, n,
                )

        return total
