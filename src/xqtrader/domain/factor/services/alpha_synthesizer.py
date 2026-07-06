"""Alpha 合成服务 — 分层截面标准化 + 统计加权合成。

合成架构（参照 Barra/Citadel 等业界主流框架）：
  第一层：组内合成 — 同类别因子等权平均，消除组内共线性
          → 独立落库为 composite_value / composite_momentum / ... 因子
  第二层：跨组加权 — 按组内合成因子的 IC/ICIR 加权合成最终 composite_alpha 因子

合成配置从注册表动态加载：
  - composite_factor_ids: 组内输入因子列表（血缘信息）
  - composite_method: 合成方式（equal_weight / icir_weight）
  - category: composite_group（组内）/ composite_cross（跨组）
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from scipy.stats import spearmanr  # type: ignore[import-untyped]

from framework.commons.logger import get_logger
from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry
from xqtrader.domain.factor.services.cross_section_reader import CrossSectionReader
from xqtrader.domain.factor.services.factor_dedup import dedup_by_correlation

logger = get_logger(__name__)

# 因子数据门禁阈值（与评估任务一致）
_MIN_FACTOR_ROWS = 1000  # 最少有效数据行数（低于此值视为数据不完整）
_MIN_COVERAGE = 0.80  # 最低覆盖率阈值（80%）

# 组名 → 组内合成因子 factor_id 映射（用于跨组合成时识别组内因子）
GROUP_FACTOR_ID_MAP: dict[str, str] = {
    "value": "composite_value",
    "momentum": "composite_momentum",
    "volatility": "composite_volatility",
    "liquidity": "composite_liquidity",
    "technical": "composite_technical",
    "fund_flow": "composite_fund_flow",
}


async def build_group_factor_ids() -> dict[str, list[str]]:
    """从注册表动态构建组内因子列表，消除硬编码。

    优先从注册表 is_composite=1 的因子读取 composite_factor_ids 血缘，
    无血缘配置时使用 GROUP_FACTOR_ID_MAP 反向映射 category → group_name。
    """
    from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry

    result: dict[str, list[str]] = {}
    registry_groups: set[str] = set()
    composites = await FacFactorRegistry.filter(is_composite=1)
    for c in composites:
        if not c.factor_id.startswith("composite_"):
            continue
        # 从 composite_factor_id 反推组名
        group_name = None
        for gname, composite_fid in GROUP_FACTOR_ID_MAP.items():
            if c.factor_id == composite_fid:
                group_name = gname
                break
        if not group_name:
            continue

        child_ids_str = c.composite_factor_ids or ""
        if child_ids_str:
            result[group_name] = [fid.strip() for fid in child_ids_str.split(",") if fid.strip()]
            registry_groups.add(group_name)

    # 补充注册表中无血缘配置的组（按 category 推断）
    category_map: dict[str, str] = {
        "value": "value", "momentum": "momentum", "volatility": "volatility",
        "liquidity": "liquidity", "technical": "technical", "fund_flow": "fund_flow",
        "fundamental": "value", "risk": "volatility",
        "tech_volatility": "volatility", "tech_oscillator": "technical",
        "tech_trend": "technical", "tech_volume": "liquidity",
    }
    all_factors = await FacFactorRegistry.filter(
        status="active",
        category__in=list(category_map.keys()),
    )
    for f in all_factors:
        mapped_group: str | None = category_map.get(f.category or "")
        if not mapped_group or mapped_group in registry_groups:
            continue
        result.setdefault(mapped_group, []).append(f.factor_id)

    return result


class AlphaSynthesizer:
    """Alpha 合成服务 — 分层截面标准化后统计加权合成。"""

    def __init__(self, reader: CrossSectionReader | None = None) -> None:
        self._reader = reader or CrossSectionReader()

    async def synthesize_pool(
        self,
        pool_id: str,
        factor_ids: list[str],
        start_date: date,
        end_date: date,
        window: int = 504,
        composite_configs: dict[str, dict] | None = None,
    ) -> dict[str, pd.DataFrame]:
        """合成单个样本池的合成因子。

        两阶段合成：
          1. 组内等权合成：同类别因子等权平均，消除组内共线性
             → 独立落库为 composite_value / composite_momentum / ... 因子
          2. 跨组ICIR加权合成：按组内合成因子的滚动 ICIR 加权
             → 最终 composite_alpha 因子

        Args:
            pool_id: 样本池标识
            factor_ids: 输入因子 ID 列表
            start_date: 起始日期
            end_date: 结束日期
            window: IC 滚动窗口
            composite_configs: 合成因子配置 {factor_id: {"composite_factor_ids": str, "composite_method": str}}
                              从注册表加载，为 None 时使用默认分组

        Returns:
            {factor_id: MultiIndex(trade_date, symbol) DataFrame}
        """
        if composite_configs is not None and not composite_configs:
            composite_configs = None

        # 1. 加载样本池标的 + 行业映射 + 市值映射
        symbols = await self._reader.load_pool_symbols(pool_id)
        if not symbols:
            logger.warning("[alpha.synth] 样本池 %s 无标的，跳过", pool_id)
            return {}

        industry_map = await self._reader.load_industry_map(symbols)
        market_cap_panel = await self._reader.load_market_cap_panel(symbols, start_date, end_date)

        # 2. 加载收益率面板
        returns_panel = await self._reader.load_returns_panel(
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
        )
        if returns_panel.empty:
            logger.warning("[alpha.synth] 样本池 %s 收益率数据为空，跳过", pool_id)
            return {}

        # 3. 逐因子加载截面面板（截面预处理：缺失值填充→MAD→Z-score→行业+市值中性化→再Z-score）
        # 门禁管控：因子数据必须完整（数据量≥1000行、覆盖率≥80%、无 Infinity），否则跳过
        # 因子级 start_date：受数据源限制的因子（如 fund_flow 自 2023-09-11 起）使用自身起始日期
        data_start_map = await self._load_data_start_map(factor_ids)

        factor_panels: dict[str, pd.Series] = {}
        for fid in factor_ids:
            factor_data_start = data_start_map.get(fid)
            effective_start = max(start_date, factor_data_start) if factor_data_start else start_date

            panel = await self._reader.load_single_factor_panel(
                start_date=effective_start,
                end_date=end_date,
                pool_id=pool_id,
                symbols=symbols,
                factor_id=fid,
                industry_map=industry_map,
                market_cap_panel=market_cap_panel,
            )
            if panel.empty or fid not in panel.columns:
                logger.debug("[alpha.synth] 因子 %s 数据为空，跳过", fid)
                continue

            # 数据门禁检查
            series = panel[fid]
            total_cells = len(series)
            non_null = int(series.notna().sum())
            coverage = float(non_null / total_cells) if total_cells > 0 else 0.0

            if total_cells < _MIN_FACTOR_ROWS:
                logger.warning(
                    "[alpha.synth] pool=%s factor=%s 门禁拦截: 数据量不足 rows=%d < 阈值=%d",
                    pool_id, fid, total_cells, _MIN_FACTOR_ROWS,
                )
                continue

            if coverage < _MIN_COVERAGE:
                logger.warning(
                    "[alpha.synth] pool=%s factor=%s 门禁拦截: 覆盖率不足 coverage=%.2f < 阈值=%.2f",
                    pool_id, fid, coverage, _MIN_COVERAGE,
                )
                continue

            if np.isinf(series.dropna()).any():
                logger.warning(
                    "[alpha.synth] pool=%s factor=%s 门禁拦截: 存在 Infinity 值",
                    pool_id, fid,
                )
                continue

            factor_panels[fid] = series

        if len(factor_panels) < 2:
            logger.warning(
                "[alpha.synth] 样本池 %s 有效因子不足 2 个(%d)，跳过",
                pool_id, len(factor_panels),
            )
            return {}

        logger.info(
            "[alpha.synth] pool=%s 加载完成: factors=%d, symbols=%d",
            pool_id, len(factor_panels), len(symbols),
        )

        # 4. 合并因子面板为宽表
        combined = pd.DataFrame(factor_panels)
        # 对齐收益率面板的索引
        common_idx = combined.index.intersection(returns_panel.index)
        combined = combined.loc[common_idx]
        returns_aligned = returns_panel.loc[common_idx]

        if combined.empty:
            logger.warning("[alpha.synth] pool=%s 合并后面板为空", pool_id)
            return {}

        composite_configs = self._resolve_composite_configs(
            composite_configs, set(factor_panels.keys()),
        )

        # 5. 第一阶段：组内等权合成（独立落库）
        icir_rank = await self._load_icir_rank(pool_id, list(factor_panels.keys()))
        group_factor_ids = await build_group_factor_ids() if not composite_configs else None
        group_alphas = self._synthesize_within_groups(
            combined, composite_configs, group_factor_ids, icir_rank,
        )
        if not group_alphas:
            return {}

        results: dict[str, pd.DataFrame] = {}
        # 组内 Alpha 独立落库（group_alphas 的 key 均为 composite_fid）
        for composite_fid, group_series in group_alphas.items():
            results[composite_fid] = group_series.to_frame(composite_fid)

        # 5.5 D4 交互因子合成（截面 Z-score 后两两相乘，独立落库）
        interaction_results = self._synthesize_interactions(combined, composite_configs)
        results.update(interaction_results)

        # 6. 第二阶段：跨组加权合成最终 alpha
        group_combined = pd.DataFrame(group_alphas)

        # 对齐收益率面板
        common_idx2 = group_combined.index.intersection(returns_aligned.index)
        group_combined = group_combined.loc[common_idx2]
        returns_aligned2 = returns_aligned.loc[common_idx2]

        ic_weights = self._calc_rolling_ic_weights(group_combined, returns_aligned2, window)

        ic_mean_w = ic_weights.get("ic_mean", {})
        icir_w = ic_weights.get("icir", {})

        # 优先使用 ICIR 加权（更稳健），无足够 IC 历史时退化为等权
        if icir_w:
            results["composite_alpha"] = self._synthesize_weighted(group_combined, icir_w, "composite_alpha")
        elif ic_mean_w:
            results["composite_alpha"] = self._synthesize_weighted(group_combined, ic_mean_w, "composite_alpha")
        else:
            results["composite_alpha"] = self._synthesize_equal_weight(group_combined, "composite_alpha")

        for factor_id, df in results.items():
            logger.info(
                "[alpha.synth] pool=%s factor=%s rows=%d non_nan=%d",
                pool_id, factor_id, len(df), int(df.iloc[:, 0].notna().sum()),
            )

        return results

    @staticmethod
    async def _load_data_start_map(factor_ids: list[str]) -> dict[str, date | None]:
        """从注册表加载因子数据起始日期。

        受数据源限制的因子（如 fund_flow 自 2023-09-11 起）有非 NULL 的 data_start_date，
        用于在加载因子面板时取 max(global_start, factor_data_start) 避免覆盖率门禁拦截。
        """
        if not factor_ids:
            return {}
        rows = await FacFactorRegistry.filter(factor_id__in=factor_ids)
        return {r.factor_id: r.data_start_date for r in rows}

    @staticmethod
    async def _load_icir_rank(pool_id: str, factor_ids: list[str]) -> dict[str, float]:
        """从 fac_factor_stats 加载样本池内因子 ICIR，供去冗余排序。"""
        from xqtrader.domain.factor.models.factor_stats import FacFactorStats

        if not factor_ids:
            return {}
        stats = await FacFactorStats.filter(
            pool_id=pool_id,
            factor_id__in=factor_ids,
        )
        rank: dict[str, float] = {}
        for s in stats:
            if s.icir is not None:
                rank[s.factor_id] = float(s.icir)
        return rank

    @staticmethod
    def _resolve_composite_configs(
        composite_configs: dict[str, dict] | None,
        loaded_factor_ids: set[str],
    ) -> dict[str, dict] | None:
        """将注册表血缘与本次实际加载的输入因子对齐，无交集时返回 None 走默认分组。"""
        if not composite_configs:
            return None
        effective: dict[str, dict] = {}
        for composite_fid, cfg in composite_configs.items():
            if composite_fid == "composite_alpha":
                continue
            child_ids = [
                fid.strip()
                for fid in (cfg.get("composite_factor_ids") or "").split(",")
                if fid.strip()
            ]
            matched = [fid for fid in child_ids if fid in loaded_factor_ids]
            if matched:
                effective[composite_fid] = {
                    **cfg,
                    "composite_factor_ids": ",".join(matched),
                }
        return effective or None

    @staticmethod
    def _synthesize_within_groups(
        factor_panel: pd.DataFrame,
        composite_configs: dict[str, dict] | None = None,
        group_factor_ids: dict[str, list[str]] | None = None,
        icir_rank: dict[str, float] | None = None,
    ) -> dict[str, pd.Series]:
        """组内等权合成：同类别因子等权平均，消除组内共线性。

        优先从 composite_configs 读取配置（注册表血缘），无配置时按 group_factor_ids 分组。

        Args:
            factor_panel: MultiIndex(trade_date, symbol), columns = factor_ids
            composite_configs: {composite_factor_id: {"composite_factor_ids": str, "composite_method": str}}
            group_factor_ids: {group_name: [factor_id, ...]} 从注册表动态构建的分组映射

        Returns:
            {composite_factor_id: Series(MultiIndex)} 每个组的组内 Alpha
        """
        group_alphas: dict[str, pd.Series] = {}

        if composite_configs:
            # 从注册表配置动态分组
            for composite_fid, config in composite_configs.items():
                if composite_fid == "composite_alpha":
                    continue  # 跨组合成因子不参与组内合成
                child_ids_str = config.get("composite_factor_ids", "")
                if not child_ids_str:
                    continue
                child_ids = [fid.strip() for fid in child_ids_str.split(",") if fid.strip()]
                # 只取因子面板中存在的因子，组内去冗余
                available = [fid for fid in child_ids if fid in factor_panel.columns]
                if icir_rank:
                    available = dedup_by_correlation(
                        available, factor_panel, icir_rank,
                    )
                if not available:
                    continue
                group_alpha = factor_panel[available].mean(axis=1)
                group_alphas[composite_fid] = group_alpha
                logger.debug(
                    "[alpha.synth] 组内合成: composite=%s factors=%d",
                    composite_fid, len(available),
                )
        else:
            # 无配置时按 group_factor_ids 分组（从注册表动态构建）
            if not group_factor_ids:
                logger.warning("[alpha.synth] 无 composite_configs 且无 group_factor_ids，跳过组内合成")
                return group_alphas

            group_factors: dict[str, list[str]] = {}
            for group_name, default_fids in group_factor_ids.items():
                composite_fid = GROUP_FACTOR_ID_MAP.get(group_name, f"composite_{group_name}")
                available = [fid for fid in default_fids if fid in factor_panel.columns]
                if icir_rank:
                    available = dedup_by_correlation(
                        available, factor_panel, icir_rank,
                    )
                if available:
                    group_factors[composite_fid] = available

            for composite_fid, fids in group_factors.items():
                group_alpha = factor_panel[fids].mean(axis=1)
                group_alphas[composite_fid] = group_alpha
                logger.debug(
                    "[alpha.synth] 组内合成(默认分组): composite=%s factors=%d",
                    composite_fid, len(fids),
                )

        logger.info(
            "[alpha.synth] 组内合成完成: composites=%s",
            {k: 1 for k in group_alphas},
        )
        return group_alphas

    @staticmethod
    def _synthesize_interactions(
        factor_panel: pd.DataFrame,
        composite_configs: dict[str, dict] | None,
    ) -> dict[str, pd.DataFrame]:
        """D4 交互因子合成 — 截面 Z-score 后两两相乘。

        从 composite_configs 中筛选 composite_method='interaction' 的合成因子，
        对其声明的两个输入因子做点对点相乘，产出交互因子面板。

        输入因子必须已由 CrossSectionReader 完成截面 Z-score 标准化。
        若任一输入因子缺失或全为 NaN，则跳过该交互因子。

        Args:
            factor_panel: MultiIndex(trade_date, symbol), columns = factor_ids
            composite_configs: {composite_factor_id: {"composite_factor_ids": str, "composite_method": str}}

        Returns:
            {interaction_factor_id: DataFrame(MultiIndex, columns=[factor_id])}
        """
        if not composite_configs or factor_panel.empty:
            return {}

        results: dict[str, pd.DataFrame] = {}
        for interaction_fid, config in composite_configs.items():
            if config.get("composite_method") != "interaction":
                continue
            child_ids_str = config.get("composite_factor_ids", "")
            if not child_ids_str:
                continue
            child_ids = [fid.strip() for fid in child_ids_str.split(",") if fid.strip()]
            if len(child_ids) != 2:
                logger.warning(
                    "[alpha.synth] 交互因子 %s 输入因子数 != 2: %s",
                    interaction_fid, child_ids,
                )
                continue
            fid_a, fid_b = child_ids
            if fid_a not in factor_panel.columns or fid_b not in factor_panel.columns:
                logger.debug(
                    "[alpha.synth] 交互因子 %s 输入缺失: %s/%s",
                    interaction_fid, fid_a, fid_b,
                )
                continue

            series_a = factor_panel[fid_a]
            series_b = factor_panel[fid_b]
            # 对齐索引后相乘
            common = series_a.index.intersection(series_b.index)
            if len(common) == 0:
                continue
            a_aligned = series_a.loc[common]
            b_aligned = series_b.loc[common]
            product = a_aligned * b_aligned
            product = product.replace([np.inf, -np.inf], np.nan).dropna()
            if product.empty:
                continue

            results[interaction_fid] = product.to_frame(interaction_fid)
            logger.debug(
                "[alpha.synth] 交互合成: %s = %s × %s rows=%d",
                interaction_fid, fid_a, fid_b, len(product),
            )

        if results:
            logger.info(
                "[alpha.synth] 交互合成完成: factors=%s",
                list(results.keys()),
            )
        return results

    @staticmethod
    def _calc_rolling_ic_weights(
        factor_panel: pd.DataFrame,
        returns_panel: pd.DataFrame,
        window: int = 504,
        min_periods: int = 20,
    ) -> dict[str, dict[date, pd.Series]]:
        """计算各因子（或组内Alpha）的滚动 IC 均值和 ICIR，作为加权权重。

        Returns:
            {"ic_mean": {date: Series(factor_id->weight)}, "icir": {date: Series(factor_id->weight)}}
        """
        factor_ids = factor_panel.columns.tolist()
        dates = sorted(factor_panel.index.get_level_values("trade_date").unique())

        # 逐截面计算 IC
        ic_records: list[tuple[date, str, float]] = []
        for dt in dates:
            try:
                rv = returns_panel.xs(dt, level="trade_date")["fwd_ret_1d"].dropna()
            except KeyError:
                continue

            for fid in factor_ids:
                try:
                    fv = factor_panel.xs(dt, level="trade_date")[fid].dropna()
                except KeyError:
                    continue

                common = fv.index.intersection(rv.index)
                if len(common) < min_periods:
                    continue

                fv_vals = fv.reindex(common).values
                rv_vals = rv.reindex(common).values
                valid = np.isfinite(fv_vals) & np.isfinite(rv_vals)
                if valid.sum() < min_periods:
                    continue

                corr, _ = spearmanr(fv_vals[valid], rv_vals[valid])
                if np.isfinite(corr):
                    ic_records.append((dt, fid, corr))

        if not ic_records:
            return {"ic_mean": {}, "icir": {}}

        ic_df = pd.DataFrame(ic_records, columns=["trade_date", "factor_id", "ic"])
        ic_df = ic_df.pivot(index="trade_date", columns="factor_id", values="ic").sort_index()

        # 滚动计算 IC 均值和 ICIR
        rolling_ic_mean = ic_df.rolling(window=window, min_periods=min_periods).mean()
        rolling_ic_std = ic_df.rolling(window=window, min_periods=min_periods).std()
        rolling_icir = rolling_ic_mean / rolling_ic_std.replace(0, np.nan)

        # 转为 {date: Series} 格式
        ic_mean_weights: dict[date, pd.Series] = {}
        icir_weights: dict[date, pd.Series] = {}

        for dt in rolling_ic_mean.index:
            ic_row = rolling_ic_mean.loc[dt].dropna()
            icir_row = rolling_icir.loc[dt].dropna()

            if len(ic_row) >= 2:
                ic_mean_weights[dt] = ic_row.abs()
            if len(icir_row) >= 2:
                icir_weights[dt] = icir_row.abs()

        return {"ic_mean": ic_mean_weights, "icir": icir_weights}

    @staticmethod
    def _synthesize_equal_weight(
        factor_panel: pd.DataFrame,
        factor_id: str = "composite_alpha",
    ) -> pd.DataFrame:
        """等权合成：所有因子等权平均。"""
        result = factor_panel.mean(axis=1).to_frame(factor_id)
        return result

    @staticmethod
    def _synthesize_weighted(
        factor_panel: pd.DataFrame,
        weights: dict[date, pd.Series],
        factor_id: str = "composite_alpha",
    ) -> pd.DataFrame:
        """加权合成：按日期截面加权。

        无权重日期退化为等权合成，避免早期日期数据丢失。

        Args:
            factor_panel: MultiIndex(trade_date, symbol), columns = factor_ids
            weights: {date: Series(factor_id -> weight)}
            factor_id: 输出列名
        """
        if not weights:
            # 无权重时退化为等权
            result = factor_panel.mean(axis=1).to_frame(factor_id)
            return result

        result_parts: list[pd.Series] = []
        dates = sorted(factor_panel.index.get_level_values("trade_date").unique())

        for dt in dates:
            try:
                cross_section = factor_panel.xs(dt, level="trade_date")
            except KeyError:
                continue

            if dt not in weights:
                # 无权重日期退化为等权
                eq_result = cross_section.mean(axis=1)  # type: ignore[call-overload]
                mi = pd.MultiIndex.from_product(
                    [[dt], eq_result.index], names=["trade_date", "symbol"],
                )
                eq_result.index = mi
                result_parts.append(eq_result)
                continue

            w = weights[dt]

            # 对齐因子列
            common_factors = cross_section.columns.intersection(w.index)
            if len(common_factors) < 1:
                continue

            cs_aligned = cross_section[common_factors]
            w_aligned = w.reindex(common_factors)
            # 对齐后重新归一化，确保权重和为1
            w_aligned = w_aligned / w_aligned.sum()

            # 加权合成
            weighted_sum = cs_aligned.multiply(w_aligned, axis=1).sum(axis=1)
            # 构造 MultiIndex(trade_date, symbol) 以便 concat 后保持一致
            mi = pd.MultiIndex.from_product(
                [[dt], weighted_sum.index], names=["trade_date", "symbol"],
            )
            weighted_sum.index = mi
            result_parts.append(weighted_sum)

        if not result_parts:
            return pd.DataFrame(columns=[factor_id])

        result_df: pd.DataFrame = pd.concat(result_parts).to_frame(factor_id)
        return result_df
