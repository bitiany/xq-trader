"""统一指标计算服务 — 接收 OHLCV DataFrame，高内聚提供所有技术指标计算。

设计要点：
- 所有指标算法（EMA/MACD/RSI/VWAP/TWAP/MA/BOLL/Donchian/TD9）统一定义于此
- 接收 pd.DataFrame（OHLCV），与数据源解耦
- 算法口径：
  * EMA：第 period 个用 SMA 初始化，前 period-1 个返回 None
  * MACD：DIF = EMA(fast) - EMA(slow), DEA = EMA(DIF, signal), MACD = (DIF-DEA)*2
  * RSI：Wilder 平滑
  * VWAP：累计 amount / (累计 volume * 100)（volume 单位为手，1 手 = 100 股）
  * TWAP：累计典型价 (H+L+C)/3 的等权平均
  * MA：简单移动平均，前 period-1 个返回 None
  * BOLL：mid = MA(period), std = 总体标准差（除以 N，与 talib.BBANDS 一致）
  * Donchian：period 内最高价/最低价
  * TD9：神奇九转，计数到 9 后停止，中断立即归零
- 所有方法返回 list[float | None]（warmup 期返回 None），保持接口统一
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

__all__ = ["IndicatorCalculator"]

_REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume", "amount")


class IndicatorCalculator:
    """统一指标计算服务，接收 OHLCV DataFrame。

    所有技术指标（EMA/MACD/RSI/VWAP/TWAP/MA/BOLL/Donchian/TD9）在此统一定义，
    避免各业务模块各自实现导致算法口径不一致。

    用法：
        calc = IndicatorCalculator.from_orm_bars(minute_bars)
        dif, dea, macd = calc.calc_macd()
        vwap = calc.calc_vwap()
    """

    def __init__(self, df: pd.DataFrame) -> None:
        """初始化。

        Args:
            df: 包含 open/high/low/close/volume/amount 列的 DataFrame，按时间升序。
                volume 单位为手（1 手 = 100 股），amount 单位为元。
        """
        self._df = df.reset_index(drop=True)
        n = len(df)
        if n == 0:
            self._closes = np.array([], dtype=float)
            self._highs = np.array([], dtype=float)
            self._lows = np.array([], dtype=float)
            self._volumes = np.array([], dtype=float)
            self._amounts = np.array([], dtype=float)
        else:
            self._closes = df["close"].to_numpy(dtype=float)
            self._highs = df["high"].to_numpy(dtype=float)
            self._lows = df["low"].to_numpy(dtype=float)
            self._volumes = df["volume"].to_numpy(dtype=float)
            self._amounts = df["amount"].to_numpy(dtype=float)

    @classmethod
    def from_dicts(cls, bars: list[dict[str, Any]]) -> IndicatorCalculator:
        """从字典列表构造。

        每个字典需包含 open/high/low/close/volume/amount 字段。
        """
        if not bars:
            df = pd.DataFrame(columns=list(_REQUIRED_COLUMNS))
        else:
            df = pd.DataFrame(bars)
            missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
            if missing:
                raise ValueError(f"bars 缺少必要字段: {missing}")
        return cls(df)

    @classmethod
    def from_orm_bars(cls, bars: list[Any]) -> IndicatorCalculator:
        """从 ORM 对象列表构造（如 CandlestickMinute）。

        每个 ORM 对象需有 open/high/low/close/volume/amount 属性。
        """
        records = [
            {
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": float(b.volume),
                "amount": float(b.amount),
            }
            for b in bars
        ]
        return cls.from_dicts(records)

    # ──────────────── EMA / MACD / RSI ────────────────

    @staticmethod
    def _ema(values: np.ndarray, period: int) -> list[float | None]:
        """EMA 内部实现，接收 numpy 数组。

        - 前 period-1 个返回 None
        - 第 period 个用 SMA 作为初始 EMA
        - 后续使用递推公式：EMA = value * (2/(period+1)) + prevEMA * (1 - 2/(period+1))
        """
        n = len(values)
        result: list[float | None] = [None] * n
        if n < period or period <= 0:
            return result
        multiplier = 2.0 / (period + 1)
        prev_ema = float(values[:period].mean())
        result[period - 1] = prev_ema
        for i in range(period, n):
            prev_ema = float(values[i]) * multiplier + prev_ema * (1 - multiplier)
            result[i] = prev_ema
        return result

    def calc_ema(self, period: int) -> list[float | None]:
        """指数移动平均。"""
        return self._ema(self._closes, period)

    def calc_macd(
        self,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> tuple[list[float | None], list[float | None], list[float | None]]:
        """MACD：DIF = EMA(fast) - EMA(slow), DEA = EMA(DIF, signal), MACD = (DIF-DEA)*2。

        Returns:
            (dif, dea, macd) 三元组
        """
        ema_fast = self._ema(self._closes, fast)
        ema_slow = self._ema(self._closes, slow)
        n = len(self._closes)

        dif: list[float | None] = []
        dif_values: list[float] = []  # None 填充为 0.0，用于 DEA 计算
        for i in range(n):
            ef = ema_fast[i]
            es = ema_slow[i]
            if ef is None or es is None:
                dif.append(None)
                dif_values.append(0.0)
            else:
                d = ef - es
                dif.append(d)
                dif_values.append(d)

        dea = self._ema(np.array(dif_values, dtype=float), signal)

        macd: list[float | None] = []
        for i in range(n):
            d_val = dif[i]
            e_val = dea[i]
            if d_val is None or e_val is None:
                macd.append(None)
            else:
                macd.append((d_val - e_val) * 2)
        return dif, dea, macd

    def calc_rsi(self, period: int = 14) -> list[float | None]:
        """RSI（Wilder 平滑）。

        - 第 0 个返回 None
        - 第 1 ~ period-2 个返回 None（累计阶段）
        - 第 period-1 个用 SMA 初始化 avgGain/avgLoss（Wilder 约定：除以 period）
        - 后续使用 Wilder 平滑：avg = (prev_avg * (period-1) + current) / period
        """
        closes = self._closes
        n = len(closes)
        result: list[float | None] = [None] * n
        if n < period:
            return result

        deltas = np.diff(closes)  # 长度 n-1，deltas[j] = closes[j+1] - closes[j]
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        # 前 period-1 个 delta（对应 closes[1..period-1]）求和后除以 period
        avg_gain = float(gains[: period - 1].sum()) / period
        avg_loss = float(losses[: period - 1].sum()) / period
        rs = 100.0 if avg_loss == 0 else avg_gain / avg_loss
        result[period - 1] = 100 - 100 / (1 + rs)

        for i in range(period, n):
            gain = float(gains[i - 1])
            loss = float(losses[i - 1])
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period
            rs = 100.0 if avg_loss == 0 else avg_gain / avg_loss
            result[i] = 100 - 100 / (1 + rs)
        return result

    # ──────────────── VWAP / TWAP ────────────────

    def calc_vwap(self) -> list[float]:
        """累计 VWAP：cumAmount / (cumVolume * 100)。

        volume 单位为手（1 手 = 100 股），amount 单位为元。
        cum_volume == 0 时回退到当前 close，避免除零。
        """
        closes = self._closes
        if len(closes) == 0:
            return []
        cum_amount = np.cumsum(self._amounts)
        cum_volume = np.cumsum(self._volumes) * 100.0
        safe_vol = np.where(cum_volume > 0, cum_volume, 1.0)
        vwap = np.where(cum_volume > 0, cum_amount / safe_vol, closes)
        return [float(x) for x in vwap]

    def calc_twap(self) -> list[float]:
        """累计 TWAP：累计典型价 (H+L+C)/3 的等权平均。"""
        closes = self._closes
        if len(closes) == 0:
            return []
        typical = (self._highs + self._lows + closes) / 3.0
        cum_typical = np.cumsum(typical)
        counts = np.arange(1, len(closes) + 1, dtype=float)
        twap = cum_typical / counts
        return [float(x) for x in twap]

    # ──────────────── MA / BOLL / Donchian ────────────────

    def calc_ma(self, period: int) -> list[float | None]:
        """简单移动平均线。前 period-1 个返回 None。"""
        closes = self._closes
        n = len(closes)
        result: list[float | None] = [None] * n
        if n < period:
            return result
        for i in range(period - 1, n):
            result[i] = float(closes[i - period + 1 : i + 1].mean())
        return result

    def calc_boll(
        self, period: int = 20, multiplier: float = 2.0,
    ) -> dict[str, list[float | None]]:
        """布林带。

        口径与 talib.BBANDS 一致：使用总体标准差（ddof=0，除以 N）。
        upper = mid + multiplier * std, lower = mid - multiplier * std。
        """
        closes = self._closes
        n = len(closes)
        if n < period:
            empty: list[float | None] = [None] * n
            return {"upper": list(empty), "mid": list(empty), "lower": list(empty)}

        s = pd.Series(closes)
        mid = s.rolling(window=period, min_periods=period).mean()
        std = s.rolling(window=period, min_periods=period).std(ddof=0)
        upper = mid + multiplier * std
        lower = mid - multiplier * std
        return {
            "upper": self._series_to_list(upper),
            "mid": self._series_to_list(mid),
            "lower": self._series_to_list(lower),
        }

    def calc_donchian(self, period: int = 20) -> dict[str, list[float | None]]:
        """唐奇安通道：period 内最高价/最低价。"""
        highs = self._highs
        lows = self._lows
        n = len(highs)
        result_upper: list[float | None] = [None] * n
        result_lower: list[float | None] = [None] * n
        if n < period:
            return {"upper": result_upper, "lower": result_lower}
        for i in range(period - 1, n):
            result_upper[i] = float(highs[i - period + 1 : i + 1].max())
            result_lower[i] = float(lows[i - period + 1 : i + 1].min())
        return {"upper": result_upper, "lower": result_lower}

    def calc_kdj(
        self,
        fastk_period: int = 9,
        slowk_period: int = 3,
        slowd_period: int = 3,
    ) -> dict[str, list[float | None]]:
        """KDJ 随机指标。

        算法与 talib.STOCH(fastk_period=9, slowk_period=3, slowd_period=3) 对齐：
        - RSV(fastk) = (close - min(low, N)) / (max(high, N) - min(low, N)) * 100
        - K(slowk) = SMA(RSV, M)：第 M 个用简单平均初始化，后续 (prev*(M-1)+curr)/M
        - D(slowd) = SMA(K, M)：同上
        - J = 3*K - 2*D
        - 极值差为 0 时 RSV 取 50，避免除零
        """
        highs = self._highs
        lows = self._lows
        closes = self._closes
        n = len(closes)
        k_result: list[float | None] = [None] * n
        d_result: list[float | None] = [None] * n
        j_result: list[float | None] = [None] * n
        if n < fastk_period:
            return {"k": k_result, "d": d_result, "j": j_result}

        # 计算 fastk（RSV）
        fastk = np.full(n, np.nan)
        for i in range(fastk_period - 1, n):
            low_min = float(lows[i - fastk_period + 1 : i + 1].min())
            high_max = float(highs[i - fastk_period + 1 : i + 1].max())
            if high_max == low_min:
                fastk[i] = 50.0
            else:
                fastk[i] = (float(closes[i]) - low_min) / (high_max - low_min) * 100.0

        # SMA 递推：第一个值用简单平均，后续用递推公式
        def _sma_recursive(values: np.ndarray, period: int) -> np.ndarray:
            result = np.full(n, np.nan)
            for i in range(period - 1, n):
                window = values[i - period + 1 : i + 1]
                if np.any(np.isnan(window)):
                    continue
                if i == period - 1:
                    result[i] = float(window.mean())
                else:
                    prev = result[i - 1]
                    if not np.isnan(prev):
                        result[i] = (prev * (period - 1) + float(values[i])) / period
            return result

        slowk = _sma_recursive(fastk, slowk_period)
        slowd = _sma_recursive(slowk, slowd_period)

        for i in range(n):
            k_val = slowk[i]
            d_val = slowd[i]
            if not np.isnan(k_val):
                k_result[i] = float(k_val)
            if not np.isnan(d_val):
                d_result[i] = float(d_val)
            if not np.isnan(k_val) and not np.isnan(d_val):
                j_result[i] = 3.0 * float(k_val) - 2.0 * float(d_val)

        return {"k": k_result, "d": d_result, "j": j_result}

    def calc_bias(self, period: int) -> list[float | None]:
        """乖离率 = (close - MA(period)) / MA(period) * 100。"""
        closes = self._closes
        n = len(closes)
        ma = self.calc_ma(period)
        result: list[float | None] = [None] * n
        for i in range(n):
            ma_val = ma[i]
            if ma_val is not None and ma_val != 0:
                result[i] = (float(closes[i]) - ma_val) / ma_val * 100.0
        return result

    # ──────────────── TD9 神奇九转 ────────────────

    def calc_td9(self) -> dict[str, list[float | None]]:
        """计算神奇九转 TD Sequential Setup。

        标准规则：
        - 买入 setup：连续 9 根 close < 4 根前 close（下跌动能衰竭）
        - 卖出 setup：连续 9 根 close > 4 根前 close（上涨动能衰竭）
        - 计数必须连续，一旦中断（close == refClose 或反向）立即归零
        - 计数到 9 后停止（不再递增），直到出现反向信号重新开始
        """
        closes = self._closes
        n = len(closes)
        buy_setup: list[float | None] = [None] * n
        sell_setup: list[float | None] = [None] * n
        buy_count = 0
        sell_count = 0
        for i in range(4, n):
            if closes[i] > closes[i - 4]:
                if sell_count < 9:
                    sell_count += 1
                    sell_setup[i] = float(sell_count)
                buy_count = 0
            elif closes[i] < closes[i - 4]:
                if buy_count < 9:
                    buy_count += 1
                    buy_setup[i] = float(buy_count)
                sell_count = 0
            else:
                buy_count = 0
                sell_count = 0
        return {"buy_setup": buy_setup, "sell_setup": sell_setup}

    # ──────────────── 辅助 ────────────────

    @staticmethod
    def _series_to_list(s: pd.Series) -> list[float | None]:
        """pandas Series 转 list[float | None]，NaN 转 None。"""
        return [None if pd.isna(v) else float(v) for v in s]
