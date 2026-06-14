"""Alpha 合成服务 — 分层截面标准化 + 统计加权合成。

合成架构（参照 Barra/Citadel 等业界主流框架）：
  第一层：组内合成 — 同类别因子等权平均，消除组内共线性
          → 独立落库为 alpha_value / alpha_momentum / ... 因子
  第二层：跨组加权 — 按组内 Alpha 的 IC/ICIR 加权合成最终 alpha 因子

分层因子组合：
  - value:      价值因子（EP/BP/DP/EV_EBITDA/SP）
  - momentum:   动量/反转因子（mom_5d/mom_20d/mom_60d/barra_momentum/barra_strev/roc_10/cs_pct_chg）
  - volatility: 波动率因子（hist_vol_10/20/60/atr_ratio/natr_14/dastd/cmra/vol_osc/downside_vol/amihud/adv_20）
  - liquidity:  流动性因子（cs_turnover/turnover_f/cs_log_amount/cs_volume_ratio/cs_log_mv）
  - technical:  技术因子（RSI/KDJ/MACD/ADX/BOLL/MA_BIAS/CCI/WR/BIAS/SAR
                + alpha158 + alpha101 + chanlun + candle_pattern）
  - fund_flow:  资金流因子（cs_main_net_pct/cs_net_mf_pct/huge_net_pct/big_net_pct）

输出因子：
  第一层（组内）：
    - alpha_value:      价值因子组
    - alpha_momentum:   动量因子组
    - alpha_volatility: 波动率因子组
    - alpha_liquidity:  流动性因子组
    - alpha_technical:  技术因子组
    - alpha_fund_flow:  资金流因子组
  第二层（跨组）：
    - alpha:            最终综合Alpha（IC/ICIR加权，退化为等权）
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from scipy.stats import spearmanr  # type: ignore[import-untyped]

from framework.commons.logger import get_logger
from xqtrader.domain.factor.services.cross_section_reader import CrossSectionReader

logger = get_logger(__name__)

# ── 分层因子组合定义 ──
# key: 组名, value: 因子ID前缀/精确匹配列表
# 组内因子等权合成，消除同组因子共线性
FACTOR_GROUPS: dict[str, list[str]] = {
    "value": [
        "ep", "bp", "dp", "ev_ebitda", "sp",
    ],
    "momentum": [
        "mom_5d", "mom_20d", "mom_60d",
        "barra_momentum", "barra_strev",
        "roc_10", "cs_pct_chg",
    ],
    "volatility": [
        "hist_vol_10", "hist_vol_20", "hist_vol_60",
        "atr_ratio", "atr_ratio_delta", "natr_14",
        "dastd", "cmra", "vol_osc",
        "downside_vol", "amihud", "adv_20",
    ],
    "liquidity": [
        "cs_turnover", "turnover_f",
        "cs_log_amount", "cs_volume_ratio", "cs_log_mv",
    ],
    "technical": [
        # 超买超卖
        "rsi_6", "rsi_14", "rsi_24", "rsi_delta_14",
        "kdj", "cci_14", "wr_14",
        "bias_6", "bias_12", "bias_24",
        # 趋势
        "macd_hist_ratio", "macd_hist_delta",
        "adx", "adx_delta", "adx_minus_di", "adx_plus_di",
        "boll_position", "boll_position_delta", "boll_width",
        "sar_deviation",
        # 均线偏离
        "ma_bias_5", "ma_bias_10", "ma_bias_20", "ma_bias_60", "ma_bias_delta_20",
        # Alpha158
        "kmid_5", "klen_5", "kup2_5", "klow2_5",
        "rsv_9", "cntp_20", "imax_20",
        "roc5_close", "std20_close", "corr_pv_10",
        # Alpha101
        "alpha_1", "alpha_12", "alpha_33", "alpha_41", "alpha_55", "alpha_101",
        # 缠论
        "chan_bi_amplitude", "chan_bi_kcount", "chan_bi_length", "chan_bi_slope",
        "chan_bi_strength", "chan_divergence_ratio", "chan_fractal_strength",
        "chan_macd_area", "chan_zs_height_ratio", "chan_zs_range",
        # K线形态
        "cdl_bull_freq_20", "cdl_bear_freq_20", "cdl_net_score_20",
        "cdl_upper_shadow_ratio", "cdl_lower_shadow_ratio", "cdl_body_ratio",
    ],
    "fund_flow": [
        "cs_main_net_pct", "cs_net_mf_pct",
        "huge_net_pct", "big_net_pct",
    ],
}

# 组名 → 组内因子 factor_id 映射
GROUP_FACTOR_ID_MAP: dict[str, str] = {
    "value": "alpha_value",
    "momentum": "alpha_momentum",
    "volatility": "alpha_volatility",
    "liquidity": "alpha_liquidity",
    "technical": "alpha_technical",
    "fund_flow": "alpha_fund_flow",
}


def _resolve_factor_group(factor_id: str) -> str:
    """将因子ID映射到其所属组。未匹配的因子归入 unclassified 组并记录警告。"""
    for group_name, group_factors in FACTOR_GROUPS.items():
        if factor_id in group_factors:
            return group_name
    # 未在分组定义中的因子归入 unclassified 组
    logger.warning("[alpha.synth] 因子 %s 未在 FACTOR_GROUPS 中定义，归入 unclassified", factor_id)
    return "unclassified"


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
        window: int = 252,
    ) -> dict[str, pd.DataFrame]:
        """合成单个样本池的 Alpha 因子。

        两阶段合成：
          1. 组内等权合成：同类别因子等权平均，消除组内共线性
             → 独立落库为 alpha_value / alpha_momentum / ... 因子
          2. 跨组加权合成：按组内 Alpha 的滚动 IC/ICIR 加权
             → 最终 alpha 因子

        Args:
            pool_id: 样本池标识
            factor_ids: 输入因子 ID 列表
            start_date: 起始日期
            end_date: 结束日期
            window: IC 滚动窗口

        Returns:
            {factor_id: MultiIndex(trade_date, symbol) DataFrame}
        """
        # 1. 加载样本池标的 + 行业映射
        symbols = await self._reader.load_pool_symbols(pool_id)
        if not symbols:
            logger.warning("[alpha.synth] 样本池 %s 无标的，跳过", pool_id)
            return {}

        industry_map = await self._reader.load_industry_map(symbols)

        # 2. 加载收益率面板
        returns_panel = await self._reader.load_returns_panel(
            start_date=start_date,
            end_date=end_date,
            symbols=symbols,
        )
        if returns_panel.empty:
            logger.warning("[alpha.synth] 样本池 %s 收益率数据为空，跳过", pool_id)
            return {}

        # 3. 逐因子加载截面面板（Z-score + 行业中性化）
        factor_panels: dict[str, pd.Series] = {}
        for fid in factor_ids:
            panel = await self._reader.load_single_factor_panel(
                start_date=start_date,
                end_date=end_date,
                pool_id=pool_id,
                symbols=symbols,
                factor_id=fid,
                industry_map=industry_map,
            )
            if panel.empty or fid not in panel.columns:
                logger.debug("[alpha.synth] 因子 %s 数据为空，跳过", fid)
                continue
            factor_panels[fid] = panel[fid]

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

        # 5. 第一阶段：组内等权合成（独立落库）
        group_alphas = self._synthesize_within_groups(combined)
        if not group_alphas:
            return {}

        results: dict[str, pd.DataFrame] = {}
        # 组内 Alpha 独立落库
        for group_name, group_series in group_alphas.items():
            factor_id = GROUP_FACTOR_ID_MAP.get(group_name, f"alpha_{group_name}")
            results[factor_id] = group_series.to_frame(factor_id)

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
            results["alpha"] = self._synthesize_weighted(group_combined, icir_w, "alpha")
        elif ic_mean_w:
            results["alpha"] = self._synthesize_weighted(group_combined, ic_mean_w, "alpha")
        else:
            results["alpha"] = self._synthesize_equal_weight(group_combined, "alpha")

        for factor_id, df in results.items():
            logger.info(
                "[alpha.synth] pool=%s factor=%s rows=%d non_nan=%d",
                pool_id, factor_id, len(df), int(df.iloc[:, 0].notna().sum()),
            )

        return results

    @staticmethod
    def _synthesize_within_groups(
        factor_panel: pd.DataFrame,
    ) -> dict[str, pd.Series]:
        """组内等权合成：同类别因子等权平均，消除组内共线性。

        Returns:
            {group_name: Series(MultiIndex)} 每个组的组内 Alpha
        """
        # 将因子按组分类
        group_factors: dict[str, list[str]] = {}
        for fid in factor_panel.columns:
            group = _resolve_factor_group(fid)
            group_factors.setdefault(group, []).append(fid)

        if not group_factors:
            return {}

        group_alphas: dict[str, pd.Series] = {}
        for group_name, fids in group_factors.items():
            # 组内等权平均
            group_alpha = factor_panel[fids].mean(axis=1)
            group_alphas[group_name] = group_alpha
            logger.debug(
                "[alpha.synth] 组内合成: group=%s factors=%d",
                group_name, len(fids),
            )

        logger.info(
            "[alpha.synth] 组内合成完成: groups=%s",
            {g: len(f) for g, f in group_factors.items()},
        )
        return group_alphas

    @staticmethod
    def _calc_rolling_ic_weights(
        factor_panel: pd.DataFrame,
        returns_panel: pd.DataFrame,
        window: int = 252,
        min_periods: int = 60,
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
        factor_id: str = "alpha",
    ) -> pd.DataFrame:
        """等权合成：所有因子等权平均。"""
        result = factor_panel.mean(axis=1).to_frame(factor_id)
        return result

    @staticmethod
    def _synthesize_weighted(
        factor_panel: pd.DataFrame,
        weights: dict[date, pd.Series],
        factor_id: str = "alpha",
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
                eq_result = cross_section.mean(axis=1)
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
