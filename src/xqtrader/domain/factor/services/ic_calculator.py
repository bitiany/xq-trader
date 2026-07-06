"""IC 计算服务 — 因子评估核心指标（IC / ICIR / 衰减半衰期 / 换手率）。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit  # type: ignore[import-untyped]
from scipy.stats import spearmanr, ttest_1samp  # type: ignore[import-untyped]

from framework.commons.logger import get_logger

logger = get_logger("factor.ic_calculator")

_MULTI_IC_HORIZONS = (5, 10, 20)

# IC 标准差下限保护阈值：
# 当 IC_std < 此值时，IC 序列过于稳定（如 diff 类因子的恒定 IC），ICIR 不可靠
# 正常因子的 IC_std 通常在 0.05~0.10，差分类因子可能 < 0.02，此处取 0.02 作为合理性下限
_MIN_IC_STD = 0.02


def _spearman_from_ranked(
    fv_rank: np.ndarray,
    rv_rank: np.ndarray,
    min_periods: int,
) -> float | None:
    """对已 rank 对齐的两组值计算 Spearman 相关（= Pearson of ranks）。

    性能优化（2026-07-04）：
      scipy.stats.spearmanr 内部含 rank 计算，每次 5-10ms（5000 标的）。
      预 rank 后用 numpy corrcoef 计算 Pearson，仅需 0.5ms，提速 10 倍。
      在 calc_decay_info 中 25,410 次 spearmanr → 25,410 次 corrcoef，节省 ~200s/因子。

    Args:
        fv_rank: 已 rank 的因子值数组
        rv_rank: 已 rank 的收益率值数组（与 fv_rank 同长度对齐）
        min_periods: 最小有效样本数

    Returns:
        Spearman 相关系数，无效返回 None
    """
    valid = np.isfinite(fv_rank) & np.isfinite(rv_rank)
    if valid.sum() < min_periods:
        return None
    fv_valid = fv_rank[valid]
    rv_valid = rv_rank[valid]
    # Pearson 相关 = 协方差 / (std_f * std_r)
    std_f = fv_valid.std()
    std_r = rv_valid.std()
    if std_f == 0 or std_r == 0:
        return None
    return float(((fv_valid - fv_valid.mean()) * (rv_valid - rv_valid.mean())).mean() / (std_f * std_r))


class ICCalculator:
    """因子 IC 及相关统计指标计算。"""

    @staticmethod
    def calc_ic_series(
        factor_panel: pd.DataFrame,
        returns_panel: pd.DataFrame,
        window: int | None = None,
        min_periods: int = 20,
        return_col: str = "fwd_ret_1d",
    ) -> pd.Series:
        """计算全量 Spearman 秩 IC 序列（不按窗口截取，截取由 calc_ic_stats 完成）。

        注意：window 参数已废弃，保留仅为兼容旧调用签名。本方法始终返回全量 IC 序列，
        forward-walk 窗口截取在 calc_ic_stats / calc_ic_significance 中按末 N 日完成。

        Args:
            factor_panel: MultiIndex (trade_date, symbol), columns = factor_ids
            returns_panel: MultiIndex (trade_date, symbol), 含 fwd_ret_*d 列
            window: 已废弃（全量计算，不截取）
            min_periods: 最小有效截面数（默认20，需小于样本池标的数）
            return_col: 前向收益列名，如 fwd_ret_1d / fwd_ret_5d

        Returns:
            Series indexed by trade_date, values = IC (float)
        """
        factor_col = factor_panel.columns[0]
        dates = factor_panel.index.get_level_values("trade_date").unique().sort_values()

        ic_records: list[tuple] = []
        for date in dates:
            try:
                fv = factor_panel.xs(date, level="trade_date")[factor_col].dropna()
                rv = returns_panel.xs(date, level="trade_date")[return_col].dropna()
            except KeyError:
                continue

            common = fv.index.intersection(rv.index)
            if len(common) < min_periods:
                continue

            fv_aligned = fv.reindex(common).values
            rv_aligned = rv.reindex(common).values

            valid = np.isfinite(fv_aligned) & np.isfinite(rv_aligned)
            n_valid = valid.sum()
            if n_valid < min_periods:
                continue

            corr, _ = spearmanr(fv_aligned[valid], rv_aligned[valid])
            if np.isfinite(corr):
                ic_records.append((date, corr))

        if not ic_records:
            return pd.Series(dtype=float, name="ic")

        return pd.Series(
            dict(ic_records),
            name="ic",
        ).sort_index()

    @staticmethod
    def calc_ic_stats(ic_series: pd.Series, window: int | None = None) -> dict:
        """计算 IC 统计指标。

        Args:
            ic_series: IC 序列（trade_date 索引）
            window: 滚动窗口（交易日数）；为 None 时使用全样本

        Returns:
            dict: ic_mean, ic_std, icir, ic_win_rate
        """
        valid = ic_series.dropna()
        valid = valid[np.isfinite(valid)]

        if valid.empty:
            return {"ic_mean": None, "ic_std": None, "icir": None, "ic_win_rate": None}

        if window is not None and window > 0 and len(valid) > window:
            valid = valid.iloc[-window:]

        ic_mean = float(valid.mean())
        ic_std = float(valid.std())
        # ICIR 计算的合理性保护：当 IC_std 过小（< 0.02）时，ICIR 不可靠
        # 典型场景：diff 类因子（如 main_net_pct_chg）的 IC 序列过于稳定，
        # IC_std=0.007 会导致 ICIR=18.39 的虚假高分。此时将 ICIR 设为 NaN，
        # 避免评级被异常值污染。
        if ic_std < _MIN_IC_STD:
            logger.info(
                "IC_std=%.4f 低于下限 %.4f，ICIR 视为不可靠 (ic_mean=%.4f, n=%d)",
                ic_std, _MIN_IC_STD, ic_mean, len(valid),
            )
            icir = np.nan
        else:
            icir = ic_mean / ic_std
        ic_win_rate = float((valid > 0).sum() / len(valid))

        return {
            "ic_mean": ic_mean,
            "ic_std": ic_std,
            "icir": icir,
            "ic_win_rate": ic_win_rate,
        }

    @staticmethod
    def calc_ic_significance(ic_series: pd.Series, window: int | None = None) -> dict[str, float | None]:
        """IC 均值显著性检验（单样本 t 检验，H0: IC=0）。"""
        valid = ic_series.dropna()
        valid = valid[np.isfinite(valid)]

        if valid.empty:
            return {"ic_tstat": None, "ic_pvalue": None}

        if window is not None and window > 0 and len(valid) > window:
            valid = valid.iloc[-window:]

        if len(valid) < 3:
            return {"ic_tstat": None, "ic_pvalue": None}

        tstat, pvalue = ttest_1samp(valid.values, 0.0)
        return {"ic_tstat": float(tstat), "ic_pvalue": float(pvalue)}

    @staticmethod
    def calc_ic_series_multi_horizon(
        factor_panel: pd.DataFrame,
        returns_panel: pd.DataFrame,
        horizons: tuple[int, ...] = _MULTI_IC_HORIZONS,
        min_periods: int = 20,
    ) -> dict[int, pd.Series]:
        """一次性计算多周期前向收益的全量 IC 序列（5/10/20 日）。

        Forward-walk 多窗口评估的预计算入口：调用方在窗口循环前调用一次，
        得到各 horizon 的全量 IC 序列，窗口循环内只需按 window 截取 stats。
        避免每个窗口都重复遍历所有 dates 计算相同的 IC 序列。

        Args:
            factor_panel: MultiIndex (trade_date, symbol), columns = factor_ids
            returns_panel: MultiIndex (trade_date, symbol), 含 fwd_ret_*d 列
            horizons: 前向收益周期列表
            min_periods: 最小有效截面数

        Returns:
            {horizon: ic_series}，ic_series 为全量序列（未截取窗口）
        """
        result: dict[int, pd.Series] = {}
        for horizon in horizons:
            col = f"fwd_ret_{horizon}d"
            if col not in returns_panel.columns:
                result[horizon] = pd.Series(dtype=float, name=f"ic_{horizon}d")
                continue
            result[horizon] = ICCalculator.calc_ic_series(
                factor_panel,
                returns_panel,
                min_periods=min_periods,
                return_col=col,
            )
        return result

    @staticmethod
    def calc_all_ic_series(
        factor_panel: pd.DataFrame,
        returns_panel: pd.DataFrame,
        horizons: tuple[int, ...] = (1, 5, 10, 20),
        min_periods: int = 20,
    ) -> dict[int, pd.Series]:
        """矢量化一次性计算所有 horizon 的 IC 序列（含 1d），共享截面数据对齐。

        性能优化（2026-07-04）：
          原实现 calc_ic_series + calc_ic_series_multi_horizon 共 4 次遍历 dates，
          每次调用 spearmanr（含内部 rank），1210 日期 × 4 = 4840 次 spearmanr。
          现合并为 1 次遍历，预计算每个日期的因子 rank，多 horizon 共用，
          用 numpy Pearson 替代 scipy spearmanr，预计提速 5-10 倍。

        Args:
            factor_panel: MultiIndex (trade_date, symbol), columns = factor_ids
            returns_panel: MultiIndex (trade_date, symbol), 含 fwd_ret_*d 列
            horizons: 前向收益周期列表（默认含 1d）
            min_periods: 最小有效截面数

        Returns:
            {horizon: ic_series}，ic_series 为全量序列（未截取窗口）
        """
        factor_col = factor_panel.columns[0]
        ret_cols = [f"fwd_ret_{h}d" for h in horizons if f"fwd_ret_{h}d" in returns_panel.columns]
        if not ret_cols:
            return {h: pd.Series(dtype=float, name=f"ic_{h}d") for h in horizons}

        dates = factor_panel.index.get_level_values("trade_date").unique().sort_values()

        # 预提取每个日期的因子 rank Series（一次 xs + rank，所有 horizon 共用）
        factor_rank_by_date: dict[Any, pd.Series] = {}
        for date in dates:
            try:
                fv = factor_panel.xs(date, level="trade_date")[factor_col].dropna()
            except KeyError:
                continue
            if len(fv) >= min_periods:
                factor_rank_by_date[date] = fv.rank()

        # 预提取每个日期的收益率 rank DataFrame（一次 xs，多 horizon 共用）
        returns_rank_by_date: dict[Any, dict[int, pd.Series]] = {}
        for date in dates:
            try:
                rv_df = returns_panel.xs(date, level="trade_date")[ret_cols]
            except KeyError:
                continue
            returns_rank_by_date[date] = {
                h: rv_df[f"fwd_ret_{h}d"].dropna().rank()
                for h in horizons
                if f"fwd_ret_{h}d" in rv_df.columns
            }

        # 计算每个 horizon 的 IC 序列
        result: dict[int, pd.Series] = {}
        for h in horizons:
            col = f"fwd_ret_{h}d"
            if col not in returns_panel.columns:
                result[h] = pd.Series(dtype=float, name=f"ic_{h}d")
                continue
            ic_records: list[tuple] = []
            for date in dates:
                fv_rank = factor_rank_by_date.get(date)
                rv_rank = returns_rank_by_date.get(date, {}).get(h)
                if fv_rank is None or rv_rank is None:
                    continue
                common = fv_rank.index.intersection(rv_rank.index)
                if len(common) < min_periods:
                    continue
                corr = _spearman_from_ranked(
                    np.asarray(fv_rank.reindex(common).values, dtype=float),
                    np.asarray(rv_rank.reindex(common).values, dtype=float),
                    min_periods,
                )
                if corr is not None and np.isfinite(corr):
                    ic_records.append((date, corr))
            if ic_records:
                result[h] = pd.Series(dict(ic_records), name=f"ic_{h}d").sort_index()
            else:
                result[h] = pd.Series(dtype=float, name=f"ic_{h}d")
        return result

    @staticmethod
    def calc_multi_horizon_ic_stats(
        ic_series_map: dict[int, pd.Series],
        window: int | None = None,
    ) -> dict[str, float | None]:
        """从已计算的多 horizon IC 序列中提取 IC 均值（按 window 截取）。

        与 calc_ic_series_multi_horizon 配合使用：
        预计算全量序列一次，各 forward-walk 窗口截取 stats。

        Args:
            ic_series_map: {horizon: ic_series}（来自 calc_ic_series_multi_horizon）
            window: forward-walk 窗口；为 None 时使用全样本

        Returns:
            {f"ic_mean_{h}d": float|None, ...}
        """
        result: dict[str, float | None] = {}
        for horizon, ic_series in ic_series_map.items():
            if ic_series.empty:
                result[f"ic_mean_{horizon}d"] = None
                continue
            ic_stats = ICCalculator.calc_ic_stats(ic_series, window=window)
            result[f"ic_mean_{horizon}d"] = ic_stats.get("ic_mean")
        return result

    @staticmethod
    def calc_multi_horizon_ic(
        factor_panel: pd.DataFrame,
        returns_panel: pd.DataFrame,
        window: int = 504,
        min_periods: int = 20,
        horizons: tuple[int, ...] = _MULTI_IC_HORIZONS,
    ) -> dict[str, float | None]:
        """计算多周期前向收益 IC 均值（5/10/20 日）。

        兼容旧调用：内部走 calc_ic_series_multi_horizon + calc_multi_horizon_ic_stats。
        新代码应直接使用上述两个方法，避免在 forward-walk 窗口循环中重复调用。
        """
        ic_series_map = ICCalculator.calc_ic_series_multi_horizon(
            factor_panel, returns_panel, horizons=horizons, min_periods=min_periods,
        )
        return ICCalculator.calc_multi_horizon_ic_stats(ic_series_map, window=window)

    @staticmethod
    def _calc_ic_decay_values(
        factor_panel: pd.DataFrame,
        returns_panel: pd.DataFrame,
        max_horizon: int = 20,
        min_periods: int = 20,
    ) -> list[tuple[int, float]]:
        """计算 IC 衰减序列 [(h, ic_mean), ...]，h=0..max_horizon。

        对每个 h，将收益率前移 h 天后计算截面 IC 的均值。
        共享方法：calc_ic_decay_curve 与 calc_decay_half_life 共用。

        性能优化（2026-07-04）：
          原实现对每个 (h, i) 调用 scipy.stats.spearmanr（含内部 rank），
          共 21 × 1210 = 25,410 次 spearmanr，单次 5-10ms，总耗时 ~200s。
          现预计算每个日期的因子 rank 和收益率 rank（共 2 × 1210 次 rank），
          用 numpy Pearson 替代 scipy spearmanr，单次 0.5ms，总耗时 ~15s。

        Args:
            factor_panel: MultiIndex (trade_date, symbol), columns = factor_ids
            returns_panel: MultiIndex (trade_date, symbol), column = 'fwd_ret_1d'
            max_horizon: 最大前移天数
            min_periods: 最小有效截面数

        Returns:
            [(h, ic_mean), ...]，ic_mean 为 NaN 表示该 horizon 无有效截面
        """
        factor_col = factor_panel.columns[0]
        dates = sorted(factor_panel.index.get_level_values("trade_date").unique())
        if len(dates) < max_horizon + 1:
            logger.warning(
                "Insufficient dates for IC decay calc: %d < %d",
                len(dates), max_horizon + 1,
            )
            return []

        # 预计算每个日期的因子 rank Series（一次 xs + rank，所有 h 共用）
        factor_rank_by_date: dict[Any, tuple[pd.Series, pd.Series]] = {}
        for date in dates:
            try:
                fv = factor_panel.xs(date, level="trade_date")[factor_col].dropna()
            except KeyError:
                continue
            if len(fv) >= min_periods:
                factor_rank_by_date[date] = (fv, fv.rank())

        # 预计算每个日期的收益率 rank Series（一次 xs + rank，所有 h 共用）
        ret_rank_by_date: dict[Any, tuple[pd.Series, pd.Series]] = {}
        for date in dates:
            try:
                rv = returns_panel.xs(date, level="trade_date")["fwd_ret_1d"].dropna()
            except KeyError:
                continue
            if len(rv) >= min_periods:
                ret_rank_by_date[date] = (rv, rv.rank())

        result: list[tuple[int, float]] = []
        for h in range(max_horizon + 1):
            ic_sum = 0.0
            ic_count = 0

            for i in range(len(dates) - h):
                date_f = dates[i]
                date_r = dates[i + h]
                fv_pair = factor_rank_by_date.get(date_f)
                rv_pair = ret_rank_by_date.get(date_r)
                if fv_pair is None or rv_pair is None:
                    continue

                fv, fv_rank = fv_pair
                rv, rv_rank = rv_pair
                common = fv.index.intersection(rv.index)
                if len(common) < min_periods:
                    continue

                corr = _spearman_from_ranked(
                    np.asarray(fv_rank.reindex(common).values, dtype=float),
                    np.asarray(rv_rank.reindex(common).values, dtype=float),
                    min_periods,
                )
                if corr is not None and np.isfinite(corr):
                    ic_sum += corr
                    ic_count += 1

            if ic_count > 0:
                result.append((h, ic_sum / ic_count))
            else:
                result.append((h, float("nan")))
        return result

    @staticmethod
    def calc_ic_decay_curve(
        factor_panel: pd.DataFrame,
        returns_panel: pd.DataFrame,
        max_horizon: int = 20,
        min_periods: int = 20,
    ) -> list[dict[str, Any]]:
        """计算 IC 衰减曲线，返回 [{"h": h, "ic": ic_value}, ...]。

        用于持久化到 fac_factor_stats.ic_decay_curve JSONB 列。
        无有效截面时返回空列表。

        Args:
            factor_panel: MultiIndex (trade_date, symbol), columns = factor_ids
            returns_panel: MultiIndex (trade_date, symbol), column = 'fwd_ret_1d'
            max_horizon: 最大前移天数
            min_periods: 最小有效截面数

        Returns:
            [{"h": 0, "ic": 0.05}, {"h": 1, "ic": 0.04}, ...]
        """
        decay_values = ICCalculator._calc_ic_decay_values(
            factor_panel, returns_panel, max_horizon, min_periods,
        )
        return ICCalculator._format_decay_curve(decay_values)

    @staticmethod
    def calc_decay_half_life(
        factor_panel: pd.DataFrame,
        returns_panel: pd.DataFrame,
        max_horizon: int = 20,
        min_periods: int = 20,
    ) -> float | None:
        """计算 IC 衰减半衰期。

        基于 _calc_ic_decay_values 得到 IC(h) 序列后，
        拟合指数衰减 IC(h) = IC(0) * exp(-lambda * h)，半衰期 = ln(2) / lambda。

        Args:
            factor_panel: MultiIndex (trade_date, symbol), columns = factor_ids
            returns_panel: MultiIndex (trade_date, symbol), column = 'fwd_ret_1d'
            max_horizon: 最大前移天数
            min_periods: 最小有效截面数

        Returns:
            半衰期（天），拟合失败返回 None
        """
        decay_values = ICCalculator._calc_ic_decay_values(
            factor_panel, returns_panel, max_horizon, min_periods,
        )
        return ICCalculator._fit_half_life(decay_values)

    @staticmethod
    def calc_decay_info(
        factor_panel: pd.DataFrame,
        returns_panel: pd.DataFrame,
        max_horizon: int = 20,
        min_periods: int = 20,
    ) -> tuple[list[dict[str, Any]], float | None]:
        """合并计算 IC 衰减曲线与半衰期（共享底层 _calc_ic_decay_values，避免重复遍历）。

        Forward-walk 多窗口评估的预计算入口：衰减曲线和半衰期不依赖 window 参数，
        应在窗口循环前调用一次，循环内直接复用结果。

        Args:
            factor_panel: MultiIndex (trade_date, symbol), columns = factor_ids
            returns_panel: MultiIndex (trade_date, symbol), column = 'fwd_ret_1d'
            max_horizon: 最大前移天数
            min_periods: 最小有效截面数

        Returns:
            (decay_curve, half_life)
            - decay_curve: [{"h": h, "ic": float|None}, ...]
            - half_life: 半衰期（天），拟合失败返回 None
        """
        decay_values = ICCalculator._calc_ic_decay_values(
            factor_panel, returns_panel, max_horizon, min_periods,
        )
        decay_curve = ICCalculator._format_decay_curve(decay_values)
        half_life = ICCalculator._fit_half_life(decay_values)
        return decay_curve, half_life

    @staticmethod
    def _format_decay_curve(
        decay_values: list[tuple[int, float]],
    ) -> list[dict[str, Any]]:
        """将 [(h, ic), ...] 格式化为 [{"h": h, "ic": float|None}, ...]。"""
        return [
            {"h": h, "ic": float(ic) if np.isfinite(ic) else None}
            for h, ic in decay_values
        ]

    @staticmethod
    def _fit_half_life(
        decay_values: list[tuple[int, float]],
    ) -> float | None:
        """从 IC 衰减序列拟合半衰期（指数衰减 IC(h) = IC(0) * exp(-lambda * h)）。

        Args:
            decay_values: [(h, ic_mean), ...]，来自 _calc_ic_decay_values

        Returns:
            半衰期（天），拟合失败返回 None
        """
        if not decay_values:
            return None

        ic_arr = np.array([ic for _, ic in decay_values])
        valid_mask = np.isfinite(ic_arr)
        if valid_mask.sum() < 3:
            return None

        x_valid = np.arange(len(ic_arr))[valid_mask]
        y_valid = ic_arr[valid_mask]

        if len(x_valid) < 3:
            return None

        def _exp_decay(x: np.ndarray, ic0: float, lam: float) -> np.ndarray:
            return ic0 * np.exp(-x * lam)

        try:
            popt, _ = curve_fit(
                _exp_decay,
                x_valid,
                y_valid,
                p0=[y_valid[0], 0.1],
                maxfev=5000,
            )
            lam = popt[1]
            if lam <= 0:
                return None
            return float(np.log(2) / lam)
        except (RuntimeError, ValueError) as e:
            logger.warning("Decay half-life fitting failed: %s", e, exc_info=True)
            return None

    @staticmethod
    def calc_turnover(factor_series: pd.DataFrame) -> float | None:
        """计算因子换手率。

        每日将因子值排名并归一化为权重（sum=1），
        换手率 = mean(|w_t - w_{t-1}|) / 2。

        Args:
            factor_series: MultiIndex (trade_date, symbol), 单因子列

        Returns:
            换手率，数据不足返回 None
        """
        factor_col = factor_series.columns[0]
        dates = sorted(factor_series.index.get_level_values("trade_date").unique())
        if len(dates) < 2:
            return None

        weights_list: list[pd.Series] = []
        for date in dates:
            try:
                fv = factor_series.xs(date, level="trade_date")[factor_col].dropna()
            except KeyError:
                continue
            fv = fv[np.isfinite(fv)]
            if fv.empty:
                continue
            ranked = fv.rank()
            w = ranked / ranked.sum()
            weights_list.append(w)

        if len(weights_list) < 2:
            return None

        turnovers: list[float] = []
        for i in range(1, len(weights_list)):
            w_curr = weights_list[i]
            w_prev = weights_list[i - 1]
            common = w_curr.index.intersection(w_prev.index)
            if common.empty:
                continue
            diff = (w_curr.reindex(common) - w_prev.reindex(common)).abs().sum() / 2
            turnovers.append(float(diff))

        if not turnovers:
            return None

        return float(np.mean(turnovers))
