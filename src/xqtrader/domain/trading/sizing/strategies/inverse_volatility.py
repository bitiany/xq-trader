"""反波动率仓位策略 — 波动率越低分配越多权重。

公式: w_i ∝ 1/σ_i，其中 σ_i 为标的年化波动率。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from framework.commons.logger import get_logger

from ...signals.fusion import FusionResult
from ..base import PortfolioState, PositionSizingStrategy, SizingContext, SizingResult
from ._helpers import compute_daily_returns, load_ohlcv

logger = get_logger(__name__)

# 波动率计算窗口
_DEFAULT_VOL_WINDOW = 20


class InverseVolatilityStrategy(PositionSizingStrategy):
    """反波动率策略 — w_i ∝ 1/σ_i。"""

    strategy_name = "inverse_volatility"

    def __init__(self) -> None:
        self._vol_window: int = _DEFAULT_VOL_WINDOW
        self._volatility: dict[str, pd.Series] = {}

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "vol_window": {
                    "type": "integer",
                    "default": _DEFAULT_VOL_WINDOW,
                    "description": "波动率计算窗口(交易日)",
                },
            },
        }

    async def prepare(self, context: SizingContext) -> None:
        self._vol_window = int(context.params.get("vol_window", _DEFAULT_VOL_WINDOW))
        ohlcv = await load_ohlcv(context.symbols, context.start_date, context.end_date)

        for symbol, df in ohlcv.items():
            returns = compute_daily_returns(df["close"])
            self._volatility[symbol] = returns.rolling(self._vol_window).std() * (252 ** 0.5)

        logger.info(
            f"InverseVolatility prepared | symbols={len(self._volatility)} | window={self._vol_window}"
        )

    def compute_weights(
        self,
        signals: dict[str, FusionResult],
        portfolio: PortfolioState,
        market_data: dict[str, pd.DataFrame] | None = None,
    ) -> dict[str, SizingResult]:
        if not signals:
            return {}

        inv_vols: dict[str, float] = {}
        for symbol in signals:
            vol = self._get_volatility(symbol, portfolio.current_date)
            if vol > 0:
                inv_vols[symbol] = 1.0 / vol
            else:
                inv_vols[symbol] = 0.0

        total_inv_vol = sum(inv_vols.values())
        if total_inv_vol <= 0:
            # 全部无波动率数据时退化为等权
            weight = 1.0 / len(signals)
            return {
                symbol: SizingResult(
                    symbol=symbol, target_weight=weight,
                    sizing_strategy=self.strategy_name, raw_score=weight,
                )
                for symbol in signals
            }

        return {
            symbol: SizingResult(
                symbol=symbol,
                target_weight=inv_vols[symbol] / total_inv_vol,
                sizing_strategy=self.strategy_name,
                raw_score=inv_vols[symbol],
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
        # 取最后一个有效值
        valid = vol_series.dropna()
        return float(valid.iloc[-1]) if not valid.empty else 0.0
