"""风险因子插件 — A1规模/A2贝塔/A3波动/A4流动性因子。

factor_id 与 definitions/risk.py A1-A4 定义完全对齐。
注意：mlev 已移至 FundamentalPlugin（B5杠杆因子）。
优先使用 ta-lib 计算技术指标。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import talib  # type: ignore[import-not-found]

from worker.plugins.factor_compute.plugins.base import FactorPlugin


class RiskPlugin(FactorPlugin):
    """风险因子插件 — Barra CNE6 风险模型因子。

    因子列表（与 FactorDefinition A1-A4 对齐）：
      A1 规模: cs_log_mv, nl_size
      A2 贝塔: beta_250, beta_down
      A3 波动: hist_vol_20, hist_vol_60, downside_vol, dastd, cmra,
               atr_14, atr_ratio, boll_width
      A4 流动性: cs_turnover, turnover_f, z_turnover, amihud, cs_log_amount,
                cs_volume_ratio, stom, stoq, adv_20, vol_osc
    """

    @property
    def factor_ids(self) -> list[str]:
        return [
            # A1 规模
            "cs_log_mv", "nl_size",
            # A2 贝塔
            "beta_250", "beta_down",
            # A3 波动
            "hist_vol_20", "hist_vol_60", "downside_vol", "dastd", "cmra",
            "atr_14", "atr_ratio", "boll_width",
            # A4 流动性
            "cs_turnover", "turnover_f", "z_turnover", "amihud",
            "cs_log_amount", "cs_volume_ratio", "stom", "stoq", "adv_20", "vol_osc",
        ]

    @property
    def category(self) -> str:
        return "risk"

    @property
    def min_periods(self) -> int:
        return 252

    def compute_batch(self, df: pd.DataFrame, ctx: dict[str, Any]) -> pd.DataFrame:
        result = pd.DataFrame()
        result["trade_date"] = df["trade_date"].values

        close = df["close"].astype(float)
        high = df["high"].astype(float) if "high" in df.columns else close
        low = df["low"].astype(float) if "low" in df.columns else close
        volume = df["volume"].astype(float) if "volume" in df.columns else pd.Series(np.nan, index=df.index)
        amount = df["amount"].astype(float) if "amount" in df.columns else pd.Series(np.nan, index=df.index)

        close_arr: np.ndarray = np.asarray(close.values, dtype=np.float64)
        high_vals = high.values if isinstance(high, pd.Series) else high.astype(float).values
        high_arr: np.ndarray = np.asarray(high_vals, dtype=np.float64)
        low_vals = low.values if isinstance(low, pd.Series) else low.astype(float).values
        low_arr: np.ndarray = np.asarray(low_vals, dtype=np.float64)

        indicator_df = ctx.get("indicator_df")

        # ---- A1 规模 ----
        # cs_log_mv / nl_size: 从 indicator_df 读取 total_mv
        if (
            indicator_df is not None
            and not indicator_df.empty
            and "trade_date" in indicator_df.columns
            and "total_mv" in indicator_df.columns
        ):
            mv_series = indicator_df.drop_duplicates(subset=["trade_date"]).set_index("trade_date")["total_mv"]
            total_mv = pd.to_numeric(result["trade_date"].map(mv_series), errors="coerce")
            result["cs_log_mv"] = np.where(total_mv > 0, np.log(total_mv), np.nan)
            # nl_size: 非线性规模 = (log_mv)^3
            # Barra 标准需对 Size 做截面回归取残差再立方，当前为简化实现（无正交化），
            # 截面正交化需跨标的数据，由后续截面阶段处理
            result["nl_size"] = np.where(total_mv > 0, np.log(total_mv) ** 3, np.nan)
        else:
            result["cs_log_mv"] = np.nan
            result["nl_size"] = np.nan

        # ---- A2 贝塔 ----
        index_kline_df = ctx.get("index_kline_df")
        if index_kline_df is not None and len(index_kline_df) > 252:
            # 合并股票和指数收益率
            stock_ret = close.pct_change()
            index_close = (
                index_kline_df.drop_duplicates(subset=["trade_date"])
                .set_index("trade_date")["close"]
                .astype(float)
            )
            index_ret = index_close.pct_change()

            # 对齐到 K线日期（用 merge 避免索引重复问题）
            ret_df = pd.DataFrame({
                "trade_date": df["trade_date"].values,
                "stock_ret": stock_ret.values,
            })
            index_ret_df = index_ret.reset_index()
            index_ret_df.columns = ["trade_date", "mkt_ret"]
            ret_df = ret_df.merge(index_ret_df, on="trade_date", how="left")
            ret_df = ret_df.set_index("trade_date")

            # 滚动 250 日 beta
            cov_roll = ret_df["stock_ret"].rolling(250).cov(ret_df["mkt_ret"])
            var_roll = ret_df["mkt_ret"].rolling(250).var()
            result["beta_250"] = np.where(var_roll > 0, cov_roll / var_roll, np.nan)

            # beta_down: 下行贝塔 — 仅用市场下跌日计算
            mkt_down = ret_df[ret_df["mkt_ret"] < 0]
            if len(mkt_down) >= 60:
                cov_down = mkt_down["stock_ret"].rolling(250, min_periods=60).cov(mkt_down["mkt_ret"])
                var_down = mkt_down["mkt_ret"].rolling(250, min_periods=60).var()
                # 将结果对齐回完整索引
                beta_down_full = pd.Series(np.nan, index=ret_df.index)
                beta_down_full.loc[mkt_down.index] = np.where(var_down > 0, cov_down / var_down, np.nan)
                result["beta_down"] = beta_down_full.values
            else:
                result["beta_down"] = np.nan
        else:
            result["beta_250"] = np.nan
            result["beta_down"] = np.nan

        # ---- A3 波动 ----
        # hist_vol_20 / hist_vol_60: 滚动标准差 × sqrt(252)
        ret = close.pct_change()
        result["hist_vol_20"] = ret.rolling(20).std() * np.sqrt(252)
        result["hist_vol_60"] = ret.rolling(60).std() * np.sqrt(252)

        # downside_vol: 下行波动率（252日窗口内负收益标准差）
        neg_ret = ret.where(ret < 0)
        result["downside_vol"] = neg_ret.rolling(252).std() * np.sqrt(252)

        # dastd: Barra 日收益加权标准差(252日) — 半衰期42天指数衰减加权
        result["dastd"] = self._ewm_std(ret, span=84) * np.sqrt(252)

        # cmra: 累积收益范围
        cum_ret = (1 + ret).cumprod()
        cum_max = cum_ret.rolling(252).max()
        cum_min = cum_ret.rolling(252).min()
        result["cmra"] = np.where(cum_min > 0, np.log(cum_max) - np.log(cum_min), np.nan)

        # ATR(14) — ta-lib
        atr_arr = talib.ATR(high_arr, low_arr, close_arr, timeperiod=14)
        result["atr_14"] = atr_arr
        result["atr_ratio"] = np.where(close_arr > 0, atr_arr / close_arr, np.nan)

        # boll_width — ta-lib BBANDS
        upper, middle, lower = talib.BBANDS(close_arr, timeperiod=20, nbdevup=2, nbdevdn=2, matype=talib.MA_Type.SMA)
        result["boll_width"] = np.where(middle > 0, (upper - lower) / middle, np.nan)

        # ---- A4 流动性 ----
        # cs_turnover / turnover_f / z_turnover: 从 indicator_df 读取
        if indicator_df is not None and not indicator_df.empty and "trade_date" in indicator_df.columns:
            ind_indexed = indicator_df.drop_duplicates(subset=["trade_date"]).set_index("trade_date")
            if "turnover_rate" in ind_indexed.columns:
                tr = pd.to_numeric(result["trade_date"].map(ind_indexed["turnover_rate"]), errors="coerce")
                result["cs_turnover"] = tr
                # z_turnover: 截面标准化换手率，当前输出原始值，
                # 截面 Z-score 需跨标的数据，由后续截面阶段统一处理
                result["z_turnover"] = tr
            else:
                result["cs_turnover"] = np.nan
                result["z_turnover"] = np.nan

            if "turnover_rate_f" in ind_indexed.columns:
                mapped_f = result["trade_date"].map(ind_indexed["turnover_rate_f"])
                result["turnover_f"] = pd.to_numeric(mapped_f, errors="coerce")
            else:
                result["turnover_f"] = np.nan
        else:
            result["cs_turnover"] = np.nan
            result["turnover_f"] = np.nan
            result["z_turnover"] = np.nan

        # amihud: 非流动性 = mean(|return| / amount, 20日)
        safe_amount = amount.where(amount != 0)
        amihud_raw = (ret.abs() / safe_amount)
        result["amihud"] = amihud_raw.rolling(20).mean()

        # cs_log_amount
        result["cs_log_amount"] = np.where(amount > 0, np.log(amount), np.nan)

        # cs_volume_ratio: 从 indicator_df 读取 volume_ratio（定义: cross_field）
        if indicator_df is not None and not indicator_df.empty and "trade_date" in indicator_df.columns:
            ind_indexed2 = indicator_df.drop_duplicates(subset=["trade_date"]).set_index("trade_date")
            if "volume_ratio" in ind_indexed2.columns:
                mapped_vr = result["trade_date"].map(ind_indexed2["volume_ratio"])
                result["cs_volume_ratio"] = pd.to_numeric(mapped_vr, errors="coerce")
            else:
                # 兜底: 从K线计算 volume / MA(volume, 20)
                vol_ma20 = volume.rolling(20).mean()
                result["cs_volume_ratio"] = np.where(vol_ma20 > 0, volume / vol_ma20, np.nan)
        else:
            vol_ma20 = volume.rolling(20).mean()
            result["cs_volume_ratio"] = np.where(vol_ma20 > 0, volume / vol_ma20, np.nan)

        # stom / stoq: 从 indicator_df 读取换手率序列做滚动求和
        if (
            indicator_df is not None
            and not indicator_df.empty
            and "trade_date" in indicator_df.columns
            and "turnover_rate" in indicator_df.columns
        ):
            tr_series = (
                indicator_df.drop_duplicates(subset=["trade_date"])
                .set_index("trade_date")["turnover_rate"]
                .sort_index()
            )
            # 对齐到K线日期
            tr_aligned = result["trade_date"].map(tr_series)
            # stom: 月换手率 = sum(turnover, 21)
            stom = tr_aligned.rolling(21).sum()
            result["stom"] = stom
            # stoq: 季换手率 = avg(STOM, 3) — Barra STOQ 定义
            result["stoq"] = stom.rolling(3).mean()
        else:
            result["stom"] = np.nan
            result["stoq"] = np.nan

        # adv_20: 20日平均成交量
        result["adv_20"] = volume.rolling(20).mean()

        # vol_osc: 量震荡 = 5日均量 / 20日均量 - 1
        vol_ma5 = volume.rolling(5).mean()
        vol_ma20_osc = volume.rolling(20).mean()
        result["vol_osc"] = np.where(vol_ma20_osc > 0, vol_ma5 / vol_ma20_osc - 1.0, np.nan)

        return self._filter_to_trade_dates(result, ctx.get("trade_dates", []))

    @staticmethod
    def _ewm_std(series: pd.Series, span: int) -> pd.Series:
        """指数衰减加权标准差。

        Args:
            series: 输入序列
            span: EWM span 参数（span ≈ 2 × 半衰期）

        Returns:
            加权标准差序列
        """
        return series.ewm(span=span, min_periods=1).std()
