"""估值因子插件 — B1价值因子，从 daily_indicator 直取或简单计算。

factor_id 与 definitions/fundamental.py B1 价值因子定义完全对齐。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from worker.plugins.factor_compute.plugins.base import FactorPlugin


class ValuationPlugin(FactorPlugin):
    """估值因子插件 — 从 daily_indicator 直接读取 + 简单派生。

    因子列表（与 FactorDefinition B1 对齐）：
      直取: pe_ttm, pb, ps_ttm, pe, ps, dv_ratio, dv_ttm
      派生: ep_ttm(=1/pe_ttm), bp(=1/pb), sp_ttm(=1/ps_ttm), cfp(=1/pcf)
    """

    # daily_indicator 直接读取: factor_id -> indicator列名
    DIRECT_READS: dict[str, str] = {
        "pe_ttm": "pe_ttm",
        "pb": "pb",
        "ps_ttm": "ps_ttm",
        "pe": "pe",
        "ps": "ps",
        "dv_ratio": "dv_ratio",
        "dv_ttm": "dv_ttm",
    }

    @property
    def factor_ids(self) -> list[str]:
        return list(self.DIRECT_READS.keys()) + [
            "ep_ttm",
            "bp",
            "sp_ttm",
            "cfp",
        ]

    @property
    def category(self) -> str:
        return "fundamental"

    @property
    def min_periods(self) -> int:
        return 1

    def compute_batch(self, df: pd.DataFrame, ctx: dict[str, Any]) -> pd.DataFrame:
        result = pd.DataFrame()
        result["trade_date"] = df["trade_date"].values

        indicator_df = ctx.get("indicator_df")

        if indicator_df is not None and not indicator_df.empty and "trade_date" in indicator_df.columns:
            ind_indexed = indicator_df.drop_duplicates(subset=["trade_date"]).set_index("trade_date")

            # 直接读取 daily_indicator 字段
            for factor_id, col_name in self.DIRECT_READS.items():
                if col_name in ind_indexed.columns:
                    result[factor_id] = pd.to_numeric(result["trade_date"].map(ind_indexed[col_name]), errors="coerce")
                else:
                    result[factor_id] = np.nan

            # 派生因子
            pe_ttm = result.get("pe_ttm")
            if pe_ttm is not None:
                result["ep_ttm"] = np.where(
                    (pe_ttm.notna()) & (pe_ttm != 0), 1.0 / pe_ttm, np.nan
                )
            else:
                result["ep_ttm"] = np.nan

            pb = result.get("pb")
            if pb is not None:
                result["bp"] = np.where(
                    (pb.notna()) & (pb != 0), 1.0 / pb, np.nan
                )
            else:
                result["bp"] = np.nan

            ps_ttm = result.get("ps_ttm")
            if ps_ttm is not None:
                result["sp_ttm"] = np.where(
                    (ps_ttm.notna()) & (ps_ttm != 0), 1.0 / ps_ttm, np.nan
                )
            else:
                result["sp_ttm"] = np.nan

            # cfp = 经营现金流/总市值 = 1/pcf（pcf=市现率=total_mv/operating_cashflow）
            if "pcf" in ind_indexed.columns:
                pcf = pd.to_numeric(result["trade_date"].map(ind_indexed["pcf"]), errors="coerce")
                result["cfp"] = np.where(
                    pcf.notna() & (pcf != 0),
                    1.0 / pcf,
                    np.nan,
                )
            else:
                result["cfp"] = np.nan
        else:
            for fid in self.factor_ids:
                result[fid] = np.nan

        return self._filter_to_trade_dates(result, ctx.get("trade_dates", []))
