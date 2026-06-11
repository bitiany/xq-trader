"""分层回测服务 — 按因子值分位数分组，评估因子选股能力。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from framework.commons.logger import get_logger

logger = get_logger(__name__)


class LayeredBacktester:
    """因子分层回测服务，通过分位数分组检验因子单调性与多空收益。"""

    def run(
        self,
        factor_panel: pd.DataFrame,
        returns_panel: pd.DataFrame,
        n_groups: int = 5,
    ) -> dict:
        """对单个因子执行分层回测。

        Args:
            factor_panel: MultiIndex (trade_date, symbol)，单因子列
            returns_panel: MultiIndex (trade_date, symbol)，列名 'fwd_ret_1d'
            n_groups: 分组数量，默认 5

        Returns:
            包含 group_returns / long_short_annual_ret / long_short_sharpe / monotonic 的字典
        """
        factor_col = factor_panel.columns[0]
        merged = factor_panel[[factor_col]].join(
            returns_panel[["fwd_ret_1d"]], how="inner"
        )
        merged = merged.dropna(subset=[factor_col, "fwd_ret_1d"])

        if merged.empty:
            logger.warning("分层回测数据为空，返回空结果")
            return {
                "group_returns": {},
                "long_short_annual_ret": 0.0,
                "long_short_sharpe": 0.0,
                "monotonic": False,
            }

        group_daily_rets: dict[int, list[float]] = {g: [] for g in range(1, n_groups + 1)}
        ls_daily_rets: list[float] = []

        for trade_date, cross in merged.groupby(level="trade_date"):
            factor_values = cross[factor_col]
            fwd_rets = cross["fwd_ret_1d"]

            group_labels = self._split_groups(factor_values, n_groups)
            for g in range(1, n_groups + 1):
                mask = group_labels == g
                if mask.any():
                    group_daily_rets[g].append(float(fwd_rets[mask].mean()))

            # 多空组合：Q5 - Q1
            q1_mask = group_labels == 1
            q5_mask = group_labels == n_groups
            if q1_mask.any() and q5_mask.any():
                ls_ret = float(fwd_rets[q5_mask].mean() - fwd_rets[q1_mask].mean())
                ls_daily_rets.append(ls_ret)

        # 各组年化收益
        group_returns: dict[str, float] = {}
        for g in range(1, n_groups + 1):
            daily = group_daily_rets[g]
            if daily:
                group_returns[f"Q{g}"] = self._calc_annual_ret(pd.Series(daily))
            else:
                group_returns[f"Q{g}"] = 0.0

        # 多空年化收益与夏普
        ls_series = pd.Series(ls_daily_rets) if ls_daily_rets else pd.Series(dtype=float)
        long_short_annual_ret = self._calc_annual_ret(ls_series) if not ls_series.empty else 0.0
        long_short_sharpe = self._calc_sharpe(ls_series) if not ls_series.empty else 0.0

        # 单调性检验：Spearman 相关系数 > 0.8
        monotonic = self._check_monotonic(group_returns)

        logger.debug(
            "分层回测完成: group_returns=%s, ls_ret=%.4f, ls_sharpe=%.4f, monotonic=%s",
            group_returns, long_short_annual_ret, long_short_sharpe, monotonic,
        )

        return {
            "group_returns": group_returns,
            "long_short_annual_ret": long_short_annual_ret,
            "long_short_sharpe": long_short_sharpe,
            "monotonic": monotonic,
        }

    def _split_groups(
        self, factor_values: pd.Series, n_groups: int
    ) -> pd.Series:
        """按分位数将因子值分为 n_groups 组。

        Args:
            factor_values: 因子值序列
            n_groups: 分组数量

        Returns:
            与输入同索引的组标签 Series（1 到 n_groups），NaN 位置为 0
        """
        valid = factor_values.dropna()
        if valid.empty:
            return pd.Series(0, index=factor_values.index, dtype=int)

        quantiles = np.linspace(0, 1, n_groups + 1)
        bins = pd.qcut(valid.rank(method="first"), q=quantiles, labels=False) + 1
        bins = bins.astype(int)

        result = pd.Series(0, index=factor_values.index, dtype=int)
        result.loc[valid.index] = bins
        return result

    def _calc_annual_ret(
        self, daily_returns: pd.Series, trading_days: int = 252
    ) -> float:
        """计算年化收益率。

        Args:
            daily_returns: 日收益率序列
            trading_days: 年交易日数

        Returns:
            年化收益率
        """
        if daily_returns.empty:
            return 0.0
        mean_ret = float(daily_returns.mean())
        return (1.0 + mean_ret) ** trading_days - 1.0

    def _calc_sharpe(
        self, daily_returns: pd.Series, trading_days: int = 252
    ) -> float:
        """计算年化夏普比率。

        Args:
            daily_returns: 日收益率序列
            trading_days: 年交易日数

        Returns:
            年化夏普比率
        """
        if daily_returns.empty or daily_returns.std() == 0:
            return 0.0
        mean_ret = float(daily_returns.mean())
        std_ret = float(daily_returns.std())
        return mean_ret / std_ret * float(np.sqrt(trading_days))

    def _check_monotonic(self, group_returns: dict[str, float]) -> bool:
        """检验组收益是否单调递增（Spearman 相关系数 > 0.8）。

        Args:
            group_returns: {Q1: ret1, Q2: ret2, ...} 各组年化收益

        Returns:
            是否单调递增
        """
        if len(group_returns) < 2:
            return False
        groups = sorted(group_returns.keys())
        ranks = list(range(1, len(groups) + 1))
        rets = [group_returns[g] for g in groups]
        corr: float = float(spearmanr(ranks, rets)[0])
        return corr > 0.8
