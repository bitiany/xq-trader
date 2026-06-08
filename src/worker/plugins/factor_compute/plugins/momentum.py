"""动量/反转因子插件 — C1动量因子。

factor_id 与 definitions/technical.py C1 定义完全对齐。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from worker.plugins.factor_compute.plugins.base import FactorPlugin


class MomentumPlugin(FactorPlugin):
    """动量/反转因子插件。

    因子列表（与 FactorDefinition C1 对齐）：
      cs_pct_chg, mom_ret5d, mom_20d, mom_60d, roc_10,
      barra_momentum, rev_5d, rev_20d, barra_strev
    """

    @property
    def factor_ids(self) -> list[str]:
        return [
            "cs_pct_chg", "mom_ret5d", "mom_20d", "mom_60d",
            "roc_10", "barra_momentum", "rev_5d", "rev_20d", "barra_strev",
        ]

    @property
    def category(self) -> str:
        return "technical"

    @property
    def min_periods(self) -> int:
        return 252  # barra_momentum needs 252 days

    def compute_batch(self, df: pd.DataFrame, ctx: dict[str, Any]) -> pd.DataFrame:
        result = pd.DataFrame()
        result["trade_date"] = df["trade_date"].values

        close = df["close"].astype(float)

        # cs_pct_chg: 从K线数据计算当日涨跌幅
        pre_close = close.shift(1)
        result["cs_pct_chg"] = np.where(pre_close > 0, close / pre_close - 1.0, np.nan)

        # 动量因子：p_now / p_then - 1
        for period, key in [(5, "mom_ret5d"), (20, "mom_20d"), (60, "mom_60d")]:
            p_then = close.shift(period)
            result[key] = np.where(p_then > 0, close / p_then - 1.0, np.nan)

        # ROC(10): 10日变化率 = close/close[-10]-1
        p_then_10 = close.shift(10)
        result["roc_10"] = np.where(p_then_10 > 0, close / p_then_10 - 1.0, np.nan)

        # Barra动量: 12月收益(剔除近1月) = (1+ret_252)/(1+ret_21) - 1
        ret_252 = np.where(close.shift(252) > 0, close / close.shift(252) - 1.0, np.nan)
        ret_21 = np.where(close.shift(21) > 0, close / close.shift(21) - 1.0, np.nan)
        result["barra_momentum"] = np.where(
            ~np.isnan(ret_252) & ~np.isnan(ret_21),
            (1 + ret_252) / (1 + ret_21) - 1.0,
            np.nan,
        )

        # 反转因子
        result["rev_5d"] = np.where(~np.isnan(result["mom_ret5d"]), -result["mom_ret5d"], np.nan)
        ret_20 = np.where(close.shift(20) > 0, close / close.shift(20) - 1.0, np.nan)
        result["rev_20d"] = np.where(~np.isnan(ret_20), -ret_20, np.nan)
        ret_21_val = np.where(close.shift(21) > 0, close / close.shift(21) - 1.0, np.nan)
        result["barra_strev"] = np.where(~np.isnan(ret_21_val), -ret_21_val, np.nan)

        return self._filter_to_trade_dates(result, ctx.get("trade_dates", []))
