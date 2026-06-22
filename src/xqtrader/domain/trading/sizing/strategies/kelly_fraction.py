"""Kelly 公式仓位策略 — 按 Kelly 公式分配权重。

公式: f = p - (1-p)/b
其中 p = 胜率, b = 平均盈利/平均亏损(盈亏比)
实际权重 = f × fraction (fraction 为 Kelly 分数，通常取半 Kelly)
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from framework.commons.logger import get_logger

from ...signals.fusion import FusionResult
from ..base import PortfolioState, PositionSizingStrategy, SizingContext, SizingResult
from ._helpers import compute_daily_returns, load_ohlcv

logger = get_logger(__name__)

_DEFAULT_VOL_WINDOW = 60
_DEFAULT_FRACTION = 0.5  # 半 Kelly


class KellyFractionStrategy(PositionSizingStrategy):
    """Kelly 公式策略 — w_i = kelly_f × fraction。"""

    strategy_name = "kelly_fraction"

    def __init__(self) -> None:
        self._vol_window: int = _DEFAULT_VOL_WINDOW
        self._fraction: float = _DEFAULT_FRACTION
        self._kelly_f: dict[str, pd.Series] = {}

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "vol_window": {"type": "integer", "default": _DEFAULT_VOL_WINDOW},
                "fraction": {"type": "number", "default": _DEFAULT_FRACTION},
            },
        }

    async def prepare(self, context: SizingContext) -> None:
        self._vol_window = int(context.params.get("vol_window", _DEFAULT_VOL_WINDOW))
        self._fraction = float(context.params.get("fraction", _DEFAULT_FRACTION))

        ohlcv = await load_ohlcv(context.symbols, context.start_date, context.end_date)
        for symbol, df in ohlcv.items():
            returns = compute_daily_returns(df["close"])
            self._kelly_f[symbol] = self._compute_rolling_kelly(returns, self._vol_window)

        logger.info(
            f"KellyFraction prepared | window={self._vol_window} | fraction={self._fraction}"
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
            kelly_f = self._get_kelly(symbol, portfolio.current_date)
            raw_weights[symbol] = max(kelly_f * self._fraction, 0.0)

        total = sum(raw_weights.values())
        if total > 1.0:
            raw_weights = {s: w / total for s, w in raw_weights.items()}
        elif total <= 0:
            # 全部 Kelly 非正时退化为等权
            weight = 1.0 / len(signals)
            return {
                symbol: SizingResult(
                    symbol=symbol, target_weight=weight,
                    sizing_strategy=self.strategy_name, raw_score=0.0,
                )
                for symbol in signals
            }

        return {
            symbol: SizingResult(
                symbol=symbol,
                target_weight=raw_weights[symbol],
                sizing_strategy=self.strategy_name,
                raw_score=raw_weights[symbol],
            )
            for symbol in signals
        }

    @staticmethod
    def _compute_rolling_kelly(returns: pd.Series, window: int) -> pd.Series:
        """计算滚动 Kelly 分数。

        f = p - (1-p)/b
        p = 胜率, b = 盈亏比 (avg_win / avg_loss)
        """
        kelly_values = []
        for i in range(len(returns)):
            if i < window:
                kelly_values.append(0.0)
                continue
            window_returns = returns.iloc[i - window:i]
            wins = window_returns[window_returns > 0]
            losses = window_returns[window_returns < 0]
            if len(wins) == 0 or len(losses) == 0:
                kelly_values.append(0.0)
                continue
            p = len(wins) / len(window_returns)
            avg_win = float(wins.mean())
            avg_loss = float(abs(losses.mean()))
            if avg_loss <= 0:
                kelly_values.append(0.0)
                continue
            b = avg_win / avg_loss
            kelly_values.append(p - (1 - p) / b)
        return pd.Series(kelly_values, index=returns.index)

    def _get_kelly(self, symbol: str, current_date: Any) -> float:
        """获取指定日期的 Kelly 分数。"""
        kelly_series = self._kelly_f.get(symbol)
        if kelly_series is None or kelly_series.empty:
            return 0.0
        if current_date in kelly_series.index:
            val = kelly_series.loc[current_date]
            return float(val) if pd.notna(val) else 0.0
        valid = kelly_series.dropna()
        return float(valid.iloc[-1]) if not valid.empty else 0.0
