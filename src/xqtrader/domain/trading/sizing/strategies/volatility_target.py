"""波动率目标仓位策略 — 按目标波动率分配权重。

公式: w_i ∝ target_vol / σ_i，总杠杆不超过 max_leverage。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from framework.commons.logger import get_logger

from ...signals.fusion import FusionResult
from ..base import PortfolioState, PositionSizingStrategy, SizingContext, SizingResult
from ._helpers import compute_daily_returns, load_ohlcv

logger = get_logger(__name__)

_DEFAULT_VOL_WINDOW = 20
_DEFAULT_TARGET_VOL = 0.15
_DEFAULT_MAX_LEVERAGE = 1.0


class VolatilityTargetStrategy(PositionSizingStrategy):
    """波动率目标策略 — w_i ∝ target_vol / σ_i。"""

    strategy_name = "volatility_target"

    def __init__(self) -> None:
        self._vol_window: int = _DEFAULT_VOL_WINDOW
        self._target_vol: float = _DEFAULT_TARGET_VOL
        self._max_leverage: float = _DEFAULT_MAX_LEVERAGE
        self._volatility: dict[str, pd.Series] = {}

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "vol_window": {"type": "integer", "default": _DEFAULT_VOL_WINDOW},
                "target_vol": {"type": "number", "default": _DEFAULT_TARGET_VOL},
                "max_leverage": {"type": "number", "default": _DEFAULT_MAX_LEVERAGE},
            },
        }

    async def prepare(self, context: SizingContext) -> None:
        self._vol_window = int(context.params.get("vol_window", _DEFAULT_VOL_WINDOW))
        self._target_vol = float(context.params.get("target_vol", _DEFAULT_TARGET_VOL))
        self._max_leverage = float(context.params.get("max_leverage", _DEFAULT_MAX_LEVERAGE))

        ohlcv = await load_ohlcv(context.symbols, context.start_date, context.end_date)
        for symbol, df in ohlcv.items():
            returns = compute_daily_returns(df["close"])
            self._volatility[symbol] = returns.rolling(self._vol_window).std() * (252 ** 0.5)

        logger.info(
            f"VolatilityTarget prepared | target={self._target_vol} | leverage={self._max_leverage}"
        )

    def compute_weights(
        self,
        signals: dict[str, FusionResult],
        portfolio: PortfolioState,
        market_data: dict[str, pd.DataFrame] | None = None,
    ) -> dict[str, SizingResult]:
        if not signals:
            return {}

        raw_weights: dict[str, float] = {}
        for symbol in signals:
            vol = self._get_volatility(symbol, portfolio.current_date)
            if vol > 0:
                raw_weights[symbol] = self._target_vol / vol
            else:
                raw_weights[symbol] = 0.0

        total = sum(raw_weights.values())
        if total > self._max_leverage:
            scale = self._max_leverage / total
            raw_weights = {s: w * scale for s, w in raw_weights.items()}

        return {
            symbol: SizingResult(
                symbol=symbol,
                target_weight=raw_weights[symbol],
                sizing_strategy=self.strategy_name,
                raw_score=raw_weights[symbol],
            )
            for symbol in signals
        }

    def _get_volatility(self, symbol: str, current_date: Any) -> float:
        """获取指定日期的波动率。"""
        vol_series = self._volatility.get(symbol)
        if vol_series is None or vol_series.empty:
            return 0.0
        if current_date in vol_series.index:
            val = vol_series.loc[current_date]
            return float(val) if pd.notna(val) else 0.0
        valid = vol_series.dropna()
        return float(valid.iloc[-1]) if not valid.empty else 0.0
