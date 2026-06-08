"""资金流因子插件 — D3资金流因子。

factor_id 与 definitions/quantitative.py D3 定义完全对齐。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from worker.plugins.factor_compute.plugins.base import FactorPlugin


class FundFlowPlugin(FactorPlugin):
    """资金流因子插件 — 从 sdc_fund_flow_individual 读取。

    因子列表（与 FactorDefinition D3 对齐）：
      cs_net_mf_amt, cs_main_net_pct, huge_net_amt, big_net_amt,
      main_net_amt, z_main_net_pct

    *_net_pct 计算策略：数据库有值直接使用，为 NULL 时通过
    net_amt / (buy_amt + sell_amt) * 100 计算。
    """

    # fund_flow_individual 直接读取: factor_id -> 列名
    DIRECT_READS: dict[str, str] = {
        "cs_net_mf_amt": "net_mf_amt",
        "cs_main_net_pct": "main_net_pct",
        "huge_net_amt": "huge_net_amt",
        "big_net_amt": "big_net_amt",
        "main_net_amt": "main_net_amt",
    }

    @property
    def factor_ids(self) -> list[str]:
        return list(self.DIRECT_READS.keys()) + ["z_main_net_pct"]

    @property
    def category(self) -> str:
        return "quantitative"

    @property
    def min_periods(self) -> int:
        return 1

    @staticmethod
    def _calc_net_pct(
        net_pct: pd.Series,
        net_amt: pd.Series,
        buy_amt: pd.Series,
        sell_amt: pd.Series,
    ) -> pd.Series:
        """计算净流入占比：有值用值，为 NULL 时通过 net_amt/(buy_amt+sell_amt)*100 计算。"""
        total = buy_amt + sell_amt
        calc_pct = np.where(total > 0, net_amt / total * 100, np.nan)
        return net_pct.fillna(pd.Series(calc_pct, index=net_pct.index))

    def compute_batch(self, df: pd.DataFrame, ctx: dict[str, Any]) -> pd.DataFrame:
        result = pd.DataFrame()
        result["trade_date"] = df["trade_date"].values

        fund_flow_df = ctx.get("fund_flow_df")

        if fund_flow_df is not None and not fund_flow_df.empty and "trade_date" in fund_flow_df.columns:
            ff_indexed = fund_flow_df.drop_duplicates(subset=["trade_date"]).set_index("trade_date")

            # 直接读取的因子（非 pct 类）
            for factor_id in ("cs_net_mf_amt", "huge_net_amt", "big_net_amt", "main_net_amt"):
                col_name = self.DIRECT_READS[factor_id]
                if col_name in ff_indexed.columns:
                    result[factor_id] = pd.to_numeric(
                        result["trade_date"].map(ff_indexed[col_name]), errors="coerce"
                    )
                else:
                    result[factor_id] = np.nan

            # cs_main_net_pct: 有值用值，无值则计算
            if "main_net_pct" in ff_indexed.columns:
                main_pct_raw = pd.to_numeric(
                    result["trade_date"].map(ff_indexed["main_net_pct"]), errors="coerce"
                )
            else:
                main_pct_raw = pd.Series(np.nan, index=result.index)

            # 计算: main_net_amt / (huge_buy_amt+huge_sell_amt+big_buy_amt+big_sell_amt) * 100
            has_buy_sell = all(
                c in ff_indexed.columns for c in ("huge_buy_amt", "huge_sell_amt", "big_buy_amt", "big_sell_amt")
            )
            if has_buy_sell:
                main_net = result["main_net_amt"]
                huge_buy = pd.to_numeric(result["trade_date"].map(ff_indexed["huge_buy_amt"]), errors="coerce")
                huge_sell = pd.to_numeric(result["trade_date"].map(ff_indexed["huge_sell_amt"]), errors="coerce")
                big_buy = pd.to_numeric(result["trade_date"].map(ff_indexed["big_buy_amt"]), errors="coerce")
                big_sell = pd.to_numeric(result["trade_date"].map(ff_indexed["big_sell_amt"]), errors="coerce")
                main_buy = huge_buy + big_buy
                main_sell = huge_sell + big_sell
                result["cs_main_net_pct"] = self._calc_net_pct(
                    main_pct_raw, main_net, main_buy, main_sell
                )
            elif main_pct_raw.notna().any():
                result["cs_main_net_pct"] = main_pct_raw
            else:
                result["cs_main_net_pct"] = np.nan

            # z_main_net_pct: 截面标准化主力净流入占比，当前输出原始值，
            # 截面 Z-score 需跨标的数据，由后续截面阶段统一处理
            result["z_main_net_pct"] = result["cs_main_net_pct"]
        else:
            for fid in self.factor_ids:
                result[fid] = np.nan

        return self._filter_to_trade_dates(result, ctx.get("trade_dates", []))
