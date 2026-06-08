"""基本面因子插件 — B2盈利/B3成长/B4质量/B5杠杆因子。

factor_id 与 definitions/fundamental.py B2-B5 定义完全对齐。
PIT 因子从 sdc_financial_indicator 读取，mlev 从 indicator_df 的 pb 派生。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from worker.plugins.factor_compute.plugins.base import FactorPlugin


class FundamentalPlugin(FactorPlugin):
    """基本面因子插件 — 从 sdc_financial_indicator PIT 读取 + mlev 从 pb 派生。

    mlev（市场杠杆）Barra 定义: total_mv / (total_mv - net_debt)。
    当前数据模型无 net_debt 字段，使用 pb（= total_mv / total_equity）作为简化近似。
    total_equity ≈ total_mv - net_debt 在大多数情况下成立，故 mlev ≈ pb。
    """

    # fina_indicator 直接读取: factor_id -> 列名
    DIRECT_READS: dict[str, str] = {
        # B2 盈利
        "roe": "roe",
        "roe_waa": "roe_waa",
        "roe_dt": "roe_dt",
        "roa": "roa",
        "roic": "roic",
        "grossprofit_margin": "grossprofit_margin",
        "netprofit_margin": "netprofit_margin",
        "eps": "eps",
        # B3 成长
        "q_or_yoy": "q_or_yoy",
        "q_netprofit_yoy": "q_netprofit_yoy",
        "q_dtprofit_yoy": "q_dtprofit_yoy",
        "q_op_yoy": "q_op_yoy",
        "q_tr_yoy": "q_tr_yoy",
        "q_ocf_yoy": "q_ocf_yoy",
        "q_roe_yoy": "q_roe_yoy",
        "q_netprofitgrow_qoq": "q_netprofitgrow_qoq",
        "q_orgrow_qoq": "q_orgrow_qoq",
        "q_opgrow_qoq": "q_opgrow_qoq",
        "q_roegrow_qoq": "q_roegrow_qoq",
        "q_equitygrow_qoq": "q_equitygrow_qoq",
        # B4 质量
        "ocf_to_profit": "ocf_to_profit",
        "ocf_to_or": "ocf_to_or",
        "salescash_to_or": "salescash_to_or",
        "dtprofit_to_profit": "dtprofit_to_profit",
        "assets_turn": "assets_turn",
        "inv_turn": "inv_turn",
        "ar_turn": "ar_turn",
        "capitalized_to_da": "capitalized_to_da",
        # B5 杠杆 (直取部分)
        "debt_to_assets": "debt_to_assets",
        "current_ratio": "current_ratio",
        "quick_ratio": "quick_ratio",
        "eqt_to_talcapital": "eqt_to_talcapital",
        "ebit_to_interest": "ebit_to_interest",
        "ocf_to_debt": "ocf_to_debt",
    }

    @property
    def factor_ids(self) -> list[str]:
        return list(self.DIRECT_READS.keys()) + ["mlev"]

    @property
    def category(self) -> str:
        return "fundamental"

    @property
    def min_periods(self) -> int:
        return 1

    def compute_batch(self, df: pd.DataFrame, ctx: dict[str, Any]) -> pd.DataFrame:
        result = pd.DataFrame()
        result["trade_date"] = df["trade_date"].values

        fina_df = ctx.get("fina_df")
        indicator_df = ctx.get("indicator_df")

        # 从 indicator_df 获取 pb（用于 mlev 派生）
        pb_series: pd.Series | None = None
        if indicator_df is not None and not indicator_df.empty and "trade_date" in indicator_df.columns:
            ind_indexed = indicator_df.drop_duplicates(subset=["trade_date"]).set_index("trade_date")
            if "pb" in ind_indexed.columns:
                pb_series = pd.to_numeric(result["trade_date"].map(ind_indexed["pb"]), errors="coerce")

        if fina_df is not None and not fina_df.empty and "ann_date" in fina_df.columns:
            # 按日PIT取值：使用 merge_asof 按 ann_date 对齐到 trade_date
            pit_aligned = self._pit_align(fina_df, result["trade_date"])

            for factor_id, col_name in self.DIRECT_READS.items():
                if col_name in pit_aligned.columns:
                    # merge_asof 后列可能为 object 类型，强制转为 float
                    result[factor_id] = pd.to_numeric(pit_aligned[col_name], errors="coerce").values
                else:
                    result[factor_id] = np.nan

            # mlev: 市场杠杆 = pb（市净率），因 pb = total_mv / total_equity
            if pb_series is not None:
                result["mlev"] = np.where(
                    pb_series.notna() & (pb_series > 0),
                    pb_series,
                    np.nan,
                )
            else:
                result["mlev"] = np.nan
        else:
            for fid in self.factor_ids:
                result[fid] = np.nan

        return self._filter_to_trade_dates(result, ctx.get("trade_dates", []))

    @staticmethod
    def _pit_align(fina_df: pd.DataFrame, trade_dates: pd.Series) -> pd.DataFrame:
        """使用 merge_asof 将财务记录按 ann_date 对齐到每个交易日。

        对每个 trade_date，取 ann_date <= trade_date 的最新财务记录。
        同一天公告多个报告期时，取最新 end_date（PIT 语义）。

        与 PITReader 对齐：fina_indicator 无 f_ann_date 列，
        仅使用 ann_date 精确模式（PITReader 一级兜底）。
        report_lag_days 兜底在 merge_asof 场景下不适用（需逐日判断），
        由 PITReader 单日查询场景覆盖。
        """
        # 准备财务数据：按 ann_date 排序，同日取最新报告期
        fina_valid = fina_df.dropna(subset=["ann_date"]).copy()
        # ann_date 从 date 转为 datetime64 以匹配 trade_date 类型
        fina_valid["ann_date"] = pd.to_datetime(fina_valid["ann_date"])
        # 同一天公告多个报告期时，保留最新 end_date
        if "end_date" in fina_valid.columns:
            fina_valid = (
                fina_valid.sort_values(["ann_date", "end_date"])
                .drop_duplicates(subset=["ann_date"], keep="last")
            )
        else:
            fina_valid = fina_valid.sort_values("ann_date").drop_duplicates(subset=["ann_date"], keep="last")

        # 构造 trade_date DataFrame（确保 datetime64 类型）
        td_df = pd.DataFrame({"trade_date": pd.to_datetime(trade_dates.values)})

        # merge_asof: 按 ann_date 向前查找
        aligned = pd.merge_asof(
            td_df,
            fina_valid,
            left_on="trade_date",
            right_on="ann_date",
            direction="backward",
        )

        return aligned
