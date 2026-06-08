"""技术因子插件 — C2趋势/C3超买超卖/C4均线因子。

factor_id 与 definitions/technical.py C2-C4 定义完全对齐。
注意：A3波动率类因子(hist_vol/atr/boll_width)由 RiskPlugin 负责。

优先使用 ta-lib 计算技术指标，ta-lib 内部维护递推状态，需全部历史K线。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import talib  # type: ignore[import-not-found]

from worker.plugins.factor_compute.plugins.base import FactorPlugin


class TechnicalPlugin(FactorPlugin):
    """技术因子插件 — 趋势/超买超卖/均线。

    因子列表（与 FactorDefinition C2-C4 对齐）：
      C2 趋势: macd_dif, macd_dea, macd_hist, adx_14, adx_plus_di, adx_minus_di,
               sar, boll_upper, boll_middle, boll_lower
      C3 超买超卖: rsi_14, kdj_k, kdj_d, kdj_j, bias_6, bias_12, bias_24,
                   cci_14, wr_14
      C4 均线: ma_5, ma_10, ma_20, ma_30, ma_60, ma_120, ma_250, ema_12
    """

    @property
    def factor_ids(self) -> list[str]:
        return [
            # C2 趋势
            "macd_dif", "macd_dea", "macd_hist",
            "adx_14", "adx_plus_di", "adx_minus_di",
            "sar", "boll_upper", "boll_middle", "boll_lower",
            # C3 超买超卖
            "rsi_14", "kdj_k", "kdj_d", "kdj_j",
            "bias_6", "bias_12", "bias_24",
            "cci_14", "wr_14",
            # C4 均线
            "ma_5", "ma_10", "ma_20", "ma_30", "ma_60", "ma_120", "ma_250",
            "ema_12",
        ]

    @property
    def category(self) -> str:
        return "technical"

    @property
    def min_periods(self) -> int:
        return 60

    @property
    def is_stateful(self) -> bool:
        return True

    def compute_batch(self, df: pd.DataFrame, ctx: dict[str, Any]) -> pd.DataFrame:
        result = pd.DataFrame()
        result["trade_date"] = df["trade_date"].values

        close = df["close"].astype(float).values
        high = df["high"].astype(float).values if "high" in df.columns else close
        low = df["low"].astype(float).values if "low" in df.columns else close
        n = len(close)

        # ---- C2 趋势 ----
        # MACD (12, 26, 9)
        macd_dif, macd_dea, macd_hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
        result["macd_dif"] = macd_dif
        result["macd_dea"] = macd_dea
        result["macd_hist"] = macd_hist

        # ADX + DI
        if n >= 28 and "high" in df.columns:
            result["adx_14"] = talib.ADX(high, low, close, timeperiod=14)
            result["adx_plus_di"] = talib.PLUS_DI(high, low, close, timeperiod=14)
            result["adx_minus_di"] = talib.MINUS_DI(high, low, close, timeperiod=14)
        else:
            result["adx_14"] = np.nan
            result["adx_plus_di"] = np.nan
            result["adx_minus_di"] = np.nan

        # SAR
        if "high" in df.columns and n >= 5:
            result["sar"] = talib.SAR(high, low, acceleration=0.02, maximum=0.20)
        else:
            result["sar"] = np.nan

        # Bollinger Bands (20, 2)
        if n >= 20:
            upper, middle, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2, matype=talib.MA_Type.SMA)
            result["boll_upper"] = upper
            result["boll_middle"] = middle
            result["boll_lower"] = lower
        else:
            result["boll_upper"] = np.nan
            result["boll_middle"] = np.nan
            result["boll_lower"] = np.nan

        # ---- C3 超买超卖 ----
        # RSI(14)
        result["rsi_14"] = talib.RSI(close, timeperiod=14)

        # KDJ — ta-lib STOCH
        if "high" in df.columns:
            slowk, slowd = talib.STOCH(high, low, close,
                fastk_period=9, slowk_period=3, slowk_matype=talib.MA_Type.EMA,
                slowd_period=3, slowd_matype=talib.MA_Type.EMA)
            result["kdj_k"] = slowk
            result["kdj_d"] = slowd
            result["kdj_j"] = 3 * slowk - 2 * slowd
        else:
            result["kdj_k"] = np.nan
            result["kdj_d"] = np.nan
            result["kdj_j"] = np.nan

        # BIAS — 偏离均线百分比
        for period, key in [(6, "bias_6"), (12, "bias_12"), (24, "bias_24")]:
            ma_val = talib.SMA(close, timeperiod=period)
            result[key] = np.where(ma_val > 0, (close - ma_val) / ma_val, np.nan)

        # CCI(14)
        if "high" in df.columns:
            result["cci_14"] = talib.CCI(high, low, close, timeperiod=14)
        else:
            result["cci_14"] = np.nan

        # WR(14)
        if "high" in df.columns:
            result["wr_14"] = talib.WILLR(high, low, close, timeperiod=14)
        else:
            result["wr_14"] = np.nan

        # ---- C4 均线 ----
        for period in [5, 10, 20, 30, 60, 120, 250]:
            key = f"ma_{period}"
            result[key] = talib.SMA(close, timeperiod=period)

        # EMA(12)
        result["ema_12"] = talib.EMA(close, timeperiod=12)

        return self._filter_to_trade_dates(result, ctx.get("trade_dates", []))
