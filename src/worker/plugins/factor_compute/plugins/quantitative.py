"""量化因子插件 — D1 Alpha101/D2 Alpha158。

factor_id 与 definitions/quantitative.py D1-D2 定义完全对齐。
D4 交互因子由 factor_compose 在截面预处理后计算，不在此处重复。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from worker.plugins.factor_compute.plugins.base import FactorPlugin


class QuantitativePlugin(FactorPlugin):
    """量化因子插件 — Alpha101 + Alpha158。

    因子列表（与 FactorDefinition D1-D2 对齐）：
      D1 Alpha101: alpha_1, alpha_12, alpha_33, alpha_41, alpha_55, alpha_101
      D2 Alpha158: kmid_5, klen_5, kup2_5, klow2_5, rsv_9,
                   cntp_20, sumd_20, imax_20, roc5_close, std20_close

    D4 交互因子（mom_vol_cross 等）由 factor_compose 在截面预处理后计算，
    不在此处重复，避免时序原始值乘积与截面 Z-score 乘积的语义冲突。
    """

    @property
    def factor_ids(self) -> list[str]:
        return [
            # D1 Alpha101
            "alpha_1", "alpha_12", "alpha_33", "alpha_41", "alpha_55", "alpha_101",
            # D2 Alpha158
            "kmid_5", "klen_5", "kup2_5", "klow2_5", "rsv_9",
            "cntp_20", "sumd_20", "imax_20", "roc5_close", "std20_close",
        ]

    @property
    def category(self) -> str:
        return "quantitative"

    @property
    def min_periods(self) -> int:
        return 60

    def compute_batch(self, df: pd.DataFrame, ctx: dict[str, Any]) -> pd.DataFrame:
        result = pd.DataFrame()
        result["trade_date"] = df["trade_date"].values

        close = df["close"].astype(float)
        open_ = df["open"].astype(float) if "open" in df.columns else close
        high = df["high"].astype(float) if "high" in df.columns else close
        low = df["low"].astype(float) if "low" in df.columns else close
        volume = df["volume"].astype(float) if "volume" in df.columns else pd.Series(np.nan, index=df.index)
        amount = df["amount"].astype(float) if "amount" in df.columns else pd.Series(np.nan, index=df.index)

        safe_vol = volume.where(volume != 0)
        vwap = (amount / safe_vol).fillna(close)

        # ---- D1 Alpha101 ----
        # Alpha#1
        ret = close.pct_change()
        std20 = ret.rolling(20).std()
        cond = np.where(ret < 0, std20, close)
        signed_power = pd.Series(cond, index=close.index) ** 2
        argmax5 = signed_power.rolling(5).apply(np.argmax, raw=True)
        result["alpha_1"] = argmax5 / 4.0 - 0.5

        # Alpha#12
        d_vol = volume.diff(1)
        d_close = close.diff(1)
        result["alpha_12"] = np.sign(d_vol) * (-d_close)

        # Alpha#33: -rank(decay_linear(close/open, 5))
        co_ratio = close / open_.where(open_ != 0)
        decay_w = np.array([2 ** i for i in range(5)]) / (2 ** 5 - 1)
        decay_co = co_ratio.rolling(5).apply(lambda x: (x * decay_w).sum(), raw=True)
        result["alpha_33"] = -decay_co.rolling(20).rank(pct=True)

        # Alpha#41
        result["alpha_41"] = np.sqrt(high * low) - vwap

        # Alpha#55: -corr(rank(close-open), rank(volume), 5)
        co_diff = close - open_
        rank_co = co_diff.rolling(5).rank(pct=True)
        rank_vol = volume.rolling(5).rank(pct=True)
        result["alpha_55"] = -rank_co.rolling(5).corr(rank_vol)

        # Alpha#101
        hl_range = high - low
        result["alpha_101"] = (close - open_) / (hl_range + 0.001)

        # ---- D2 Alpha158 ----
        # kmid_5
        body_ratio = (close - open_) / open_.where(open_ != 0)
        result["kmid_5"] = body_ratio.rolling(5).mean()

        # klen_5
        amplitude = (high - low) / open_.where(open_ != 0)
        result["klen_5"] = amplitude.rolling(5).mean()

        # kup2_5
        hl_spread = (high - low).where((high - low) != 0)
        upper_shadow = (high - pd.concat([open_, close], axis=1).max(axis=1)) / hl_spread
        result["kup2_5"] = upper_shadow.rolling(5).mean()

        # klow2_5
        lower_shadow = (pd.concat([open_, close], axis=1).min(axis=1) - low) / hl_spread
        result["klow2_5"] = lower_shadow.rolling(5).mean()

        # rsv_9
        h9 = high.rolling(9).max()
        l9 = low.rolling(9).min()
        spread9 = h9 - l9
        result["rsv_9"] = np.where(spread9 > 0, (close - l9) / spread9, np.nan)

        # cntp_20
        pos_ret = (ret > 0).astype(float)
        result["cntp_20"] = pos_ret.rolling(20).mean()

        # sumd_20
        pos_sum = ret.where(ret > 0, 0).rolling(20).sum()
        neg_sum = ret.where(ret < 0, 0).rolling(20).sum()
        result["sumd_20"] = pos_sum + neg_sum

        # imax_20: 20日内最高价位置（归一化）
        result["imax_20"] = high.rolling(20).apply(lambda x: np.argmax(x) / 19.0, raw=True)

        # roc5_close
        result["roc5_close"] = np.where(close.shift(5) > 0, close / close.shift(5) - 1.0, np.nan)

        # std20_close
        result["std20_close"] = ret.rolling(20).std()

        return self._filter_to_trade_dates(result, ctx.get("trade_dates", []))
