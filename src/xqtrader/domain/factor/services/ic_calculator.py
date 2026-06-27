"""IC 计算服务 — 因子评估核心指标（IC / ICIR / 衰减半衰期 / 换手率）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit  # type: ignore[import-untyped]
from scipy.stats import spearmanr, ttest_1samp  # type: ignore[import-untyped]

from framework.commons.logger import get_logger

logger = get_logger("factor.ic_calculator")

_MULTI_IC_HORIZONS = (5, 10, 20)


class ICCalculator:
    """因子 IC 及相关统计指标计算。"""

    @staticmethod
    def calc_ic_series(
        factor_panel: pd.DataFrame,
        returns_panel: pd.DataFrame,
        window: int = 252,
        min_periods: int = 20,
        return_col: str = "fwd_ret_1d",
    ) -> pd.Series:
        """计算滚动 Spearman 秩 IC 序列。

        Args:
            factor_panel: MultiIndex (trade_date, symbol), columns = factor_ids
            returns_panel: MultiIndex (trade_date, symbol), 含 fwd_ret_*d 列
            window: 滚动窗口（IC 序列按日计算；ICIR 在 calc_ic_stats 中取末 window 日）
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
        icir = ic_mean / ic_std if ic_std != 0 else np.nan
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
    def calc_multi_horizon_ic(
        factor_panel: pd.DataFrame,
        returns_panel: pd.DataFrame,
        window: int = 252,
        min_periods: int = 20,
        horizons: tuple[int, ...] = _MULTI_IC_HORIZONS,
    ) -> dict[str, float | None]:
        """计算多周期前向收益 IC 均值（5/10/20 日）。"""
        result: dict[str, float | None] = {}
        for horizon in horizons:
            col = f"fwd_ret_{horizon}d"
            if col not in returns_panel.columns:
                result[f"ic_mean_{horizon}d"] = None
                continue
            ic_series = ICCalculator.calc_ic_series(
                factor_panel,
                returns_panel,
                window=window,
                min_periods=min_periods,
                return_col=col,
            )
            ic_stats = ICCalculator.calc_ic_stats(ic_series, window=window)
            result[f"ic_mean_{horizon}d"] = ic_stats.get("ic_mean")
        return result

    @staticmethod
    def calc_decay_half_life(
        factor_panel: pd.DataFrame,
        returns_panel: pd.DataFrame,
        max_horizon: int = 20,
        min_periods: int = 20,
    ) -> float | None:
        """计算 IC 衰减半衰期。

        对 h = 1..max_horizon，将收益率前移 h 天后计算截面 IC，
        拟合指数衰减 IC(h) = IC(0) * exp(-lambda * h)，半衰期 = ln(2) / lambda。

        Args:
            factor_panel: MultiIndex (trade_date, symbol), columns = factor_ids
            returns_panel: MultiIndex (trade_date, symbol), column = 'fwd_ret_1d'
            max_horizon: 最大前移天数
            min_periods: 最小有效截面数

        Returns:
            半衰期（天），拟合失败返回 None
        """
        factor_col = factor_panel.columns[0]
        dates = sorted(factor_panel.index.get_level_values("trade_date").unique())
        if len(dates) < max_horizon + 1:
            logger.warning("Insufficient dates for decay half-life calc: %d < %d", len(dates), max_horizon + 1)
            return None

        ic_values: list[float] = []

        for h in range(max_horizon + 1):
            ic_sum = 0.0
            ic_count = 0

            for i in range(len(dates) - h):
                date_f = dates[i]
                date_r = dates[i + h]
                try:
                    fv = factor_panel.xs(date_f, level="trade_date")[factor_col].dropna()
                    rv = returns_panel.xs(date_r, level="trade_date")["fwd_ret_1d"].dropna()
                except KeyError:
                    continue

                common = fv.index.intersection(rv.index)
                if len(common) < min_periods:
                    continue

                fv_aligned = fv.reindex(common).values
                rv_aligned = rv.reindex(common).values
                valid = np.isfinite(fv_aligned) & np.isfinite(rv_aligned)
                if valid.sum() < min_periods:
                    continue

                corr, _ = spearmanr(fv_aligned[valid], rv_aligned[valid])
                if np.isfinite(corr):
                    ic_sum += corr
                    ic_count += 1

            if ic_count > 0:
                ic_values.append(ic_sum / ic_count)
            else:
                ic_values.append(np.nan)

        ic_arr = np.array(ic_values)
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
