"""个股技术面诊断服务 — 趋势/动量/估值，输出结构化诊断信号而非原始指标数组。"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import talib  # type: ignore[import-unfound]

from xqtrader.domain.market.models.candlestick import CandlestickDaily
from xqtrader.domain.market.models.daily_indicator import DailyIndicator
from xqtrader.domain.security.services.stock_detail_service import (
    SecurityMixin,
    StockApiFormatter,
)


def _last(arr: np.ndarray, idx: int = -1) -> float | None:
    if arr is None or len(arr) == 0:
        return None
    val = StockApiFormatter.value(arr[idx])
    if isinstance(val, (int, float)):
        return float(val)
    return None


class StockTechnicalService(SecurityMixin):
    """个股技术面诊断服务。"""

    async def get_trend(self, symbol: str, limit: int = 120) -> dict[str, Any]:
        await self._ensure_security(symbol)
        rows = await self._load_candles(symbol, limit)
        if len(rows) < 60:
            return {"symbol": symbol, "available": False, "message": "K线数据不足(需≥60条)"}
        close, high, low = self._arrays(rows)
        ma = {p: talib.MA(close, timeperiod=p) for p in [5, 10, 20, 60]}
        adx = talib.ADX(high, low, close, timeperiod=14)
        upper, mid, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
        last_close = float(close[-1])
        return {
            "symbol": symbol,
            "trade_date": self._date_str(rows[-1].trade_date),
            "available": True,
            "direction": self._trend_direction(ma, close),
            "ma_alignment": self._ma_alignment(ma, last_close),
            "ma_values": {f"ma{p}": _last(arr) for p, arr in ma.items()},
            "adx": _last(adx),
            "adx_label": self._adx_label(_last(adx)),
            "boll_position": self._boll_position(last_close, _last(upper), _last(mid), _last(lower)),
            "price_vs_ma60": self._price_vs_ma(last_close, _last(ma[60])),
        }

    async def get_momentum(self, symbol: str, limit: int = 120) -> dict[str, Any]:
        await self._ensure_security(symbol)
        rows = await self._load_candles(symbol, limit)
        if len(rows) < 35:
            return {"symbol": symbol, "available": False, "message": "K线数据不足(需≥35条)"}
        close, high, low = self._arrays(rows)
        dif, dea, macd = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
        rsi = talib.RSI(close, timeperiod=14)
        k, d = talib.STOCH(high, low, close, fastk_period=9, slowk_period=3, slowd_period=3)
        return {
            "symbol": symbol,
            "trade_date": self._date_str(rows[-1].trade_date),
            "available": True,
            "macd": {
                "dif": _last(dif), "dea": _last(dea), "hist": _last(macd * 2),
                "signal": self._macd_signal(dif, dea),
                "divergence": self._macd_divergence(close, dif),
            },
            "kdj": {
                "k": _last(k), "d": _last(d), "j": _last(3 * k - 2 * d),
                "signal": self._kdj_signal(k, d),
            },
            "rsi": {
                "rsi14": _last(rsi),
                "signal": self._rsi_signal(rsi),
            },
            "td9": self._td9_signal(close),
        }

    async def get_valuation(self, symbol: str, limit: int = 252) -> dict[str, Any]:
        await self._ensure_security(symbol)
        rows = await DailyIndicator.filter(
            symbol=symbol, order_by=DailyIndicator.trade_date.desc(), limit=limit,
        )
        if not rows:
            return {"symbol": symbol, "available": False, "message": "无估值数据"}
        rows = list(reversed(rows))
        latest = rows[-1]
        pe_hist = [r.pe_ttm for r in rows if r.pe_ttm and r.pe_ttm > 0]
        pb_hist = [r.pb for r in rows if r.pb and r.pb > 0]
        return {
            "symbol": symbol,
            "trade_date": self._date_str(latest.trade_date),
            "available": True,
            "pe_ttm": StockApiFormatter.value(latest.pe_ttm),
            "pb": StockApiFormatter.value(latest.pb),
            "ps_ttm": StockApiFormatter.value(latest.ps_ttm),
            "dv_ttm": StockApiFormatter.value(latest.dv_ttm),
            "total_mv": StockApiFormatter.value(latest.total_mv),
            "circ_mv": StockApiFormatter.value(latest.circ_mv),
            "turnover_rate": StockApiFormatter.value(latest.turnover_rate),
            "volume_ratio": StockApiFormatter.value(latest.volume_ratio),
            "pe_ttm_percentile": self._percentile(latest.pe_ttm, pe_hist),
            "pb_percentile": self._percentile(latest.pb, pb_hist),
            "valuation_label": self._valuation_label(self._percentile(latest.pe_ttm, pe_hist)),
        }

    # ---- 内部工具 ----

    async def _load_candles(self, symbol: str, limit: int) -> list[CandlestickDaily]:
        rows = await CandlestickDaily.filter(
            symbol=symbol, order_by=CandlestickDaily.trade_date.desc(), limit=limit,
        )
        return list(reversed(rows))

    @staticmethod
    def _arrays(rows: list[CandlestickDaily]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        close = np.array([r.close for r in rows], dtype=float)
        high = np.array([r.high for r in rows], dtype=float)
        low = np.array([r.low for r in rows], dtype=float)
        return close, high, low

    @staticmethod
    def _date_str(value: Any) -> str:
        if isinstance(value, date):
            return value.isoformat()
        return str(value)

    @staticmethod
    def _trend_direction(ma: dict[int, np.ndarray], close: np.ndarray) -> str:
        ma5, ma10, ma20, ma60 = _last(ma[5]), _last(ma[10]), _last(ma[20]), _last(ma[60])
        last_close = float(close[-1])
        if ma5 is None or ma10 is None or ma20 is None or ma60 is None:
            return "未知"
        if last_close > ma5 > ma10 > ma20 and last_close > ma60:
            return "多头"
        if last_close < ma5 < ma10 < ma20 and last_close < ma60:
            return "空头"
        return "震荡"

    @staticmethod
    def _ma_alignment(ma: dict[int, np.ndarray], last_close: float) -> str:
        ma5, ma10, ma20, ma60 = (_last(ma[p]) for p in [5, 10, 20, 60])
        if ma5 is None or ma10 is None or ma20 is None or ma60 is None:
            return "不完整"
        if ma5 > ma10 > ma20 > ma60 and last_close > ma5:
            return "多头排列"
        if ma5 < ma10 < ma20 < ma60 and last_close < ma5:
            return "空头排列"
        return "纠缠/交叉"

    @staticmethod
    def _adx_label(adx: float | None) -> str:
        if adx is None:
            return "未知"
        if adx >= 50:
            return "强趋势"
        if adx >= 25:
            return "趋势确立"
        return "无趋势/弱趋势"

    @staticmethod
    def _boll_position(close: float, upper: float | None, mid: float | None, lower: float | None) -> str:
        if upper is None or mid is None or lower is None:
            return "未知"
        if close >= upper:
            return "突破上轨(超买区)"
        if close <= lower:
            return "跌破下轨(超卖区)"
        if close > mid:
            return "中轨上方"
        return "中轨下方"

    @staticmethod
    def _price_vs_ma(close: float, ma60: float | None) -> str:
        if ma60 is None:
            return "未知"
        if close > ma60:
            return "站上60日线"
        return "跌破60日线"

    @staticmethod
    def _macd_signal(dif: np.ndarray, dea: np.ndarray) -> str:
        if len(dif) < 2:
            return "未知"
        prev_diff = float(dif[-2] - dea[-2])
        curr_diff = float(dif[-1] - dea[-1])
        if prev_diff <= 0 < curr_diff:
            return "金叉"
        if prev_diff >= 0 > curr_diff:
            return "死叉"
        if curr_diff > 0:
            return "多头运行" if curr_diff > prev_diff else "多头趋弱"
        return "空头运行" if curr_diff < prev_diff else "空头趋弱"

    @staticmethod
    def _macd_divergence(close: np.ndarray, dif: np.ndarray) -> str:
        if len(close) < 30:
            return "数据不足"
        recent = close[-30:]
        dif_recent = dif[-30:]
        price_higher = float(recent[-1]) > float(np.nanmax(recent[:-5]))
        dif_lower = float(dif_recent[-1]) < float(np.nanmax(dif_recent[:-5]))
        price_lower = float(recent[-1]) < float(np.nanmin(recent[:-5]))
        dif_higher = float(dif_recent[-1]) > float(np.nanmin(dif_recent[:-5]))
        if price_higher and dif_lower and float(dif_recent[-1]) > 0:
            return "顶背离"
        if price_lower and dif_higher and float(dif_recent[-1]) < 0:
            return "底背离"
        return "无背离"

    @staticmethod
    def _kdj_signal(k: np.ndarray, d: np.ndarray) -> str:
        if len(k) < 2:
            return "未知"
        k_last, d_last = _last(k), _last(d)
        k_prev, d_prev = _last(k, -2), _last(d, -2)
        if k_last is None or d_last is None or k_prev is None or d_prev is None:
            return "未知"
        if k_prev <= d_prev and k_last > d_last:
            return "金叉"
        if k_prev >= d_prev and k_last < d_last:
            return "死叉"
        if k_last > 80:
            return "超买"
        if k_last < 20:
            return "超卖"
        return "中性"

    @staticmethod
    def _rsi_signal(rsi: np.ndarray) -> str:
        last = _last(rsi)
        if last is None:
            return "未知"
        if last >= 70:
            return "超买"
        if last <= 30:
            return "超卖"
        return "中性"

    @staticmethod
    def _td9_signal(close: np.ndarray) -> dict[str, Any]:
        buy_setup = 0
        sell_setup = 0
        for i in range(4, len(close)):
            if close[i] > close[i - 4]:
                sell_setup = sell_setup + 1 if sell_setup < 9 else 1
                buy_setup = 0
            elif close[i] < close[i - 4]:
                buy_setup = buy_setup + 1 if buy_setup < 9 else 1
                sell_setup = 0
            else:
                buy_setup = 0
                sell_setup = 0
        return {
            "buy_setup_count": buy_setup,
            "sell_setup_count": sell_setup,
            "signal": "买入setup完成" if buy_setup >= 9 else ("卖出setup完成" if sell_setup >= 9 else "未完成"),
        }

    @staticmethod
    def _percentile(current: float | None, history: list[float]) -> float | None:
        if current is None or not history:
            return None
        arr = np.array(history, dtype=float)
        arr = arr[~np.isnan(arr)]
        if len(arr) == 0:
            return None
        return round(float(np.mean(arr <= current) * 100), 1)

    @staticmethod
    def _valuation_label(percentile: float | None) -> str:
        if percentile is None:
            return "未知"
        if percentile >= 80:
            return "高估"
        if percentile <= 20:
            return "低估"
        return "合理"
