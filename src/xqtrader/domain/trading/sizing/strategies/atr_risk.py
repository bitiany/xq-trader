"""ATR 风险仓位策略 — 按 ATR 风险预算分配权重。

公式: w_i = (capital × risk_pct) / (ATR_i × multiplier)
其中 ATR_i 为标的真实波幅均值，multiplier 为风险倍数。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from framework.commons.logger import get_logger

from ...signals.fusion import FusionResult
from ..base import PortfolioState, PositionSizingStrategy, SizingContext, SizingResult
from ._helpers import compute_atr, load_ohlcv

logger = get_logger(__name__)

_DEFAULT_ATR_PERIOD = 14
_DEFAULT_RISK_PCT = 0.02
_DEFAULT_MULTIPLIER = 2.0


class AtrRiskStrategy(PositionSizingStrategy):
    """ATR 风险策略 — w_i = (capital × risk_pct) / (ATR_i × multiplier)。"""

    strategy_name = "atr_risk"

    def __init__(self) -> None:
        self._atr_period: int = _DEFAULT_ATR_PERIOD
        self._risk_pct: float = _DEFAULT_RISK_PCT
        self._multiplier: float = _DEFAULT_MULTIPLIER
        self._atr: dict[str, pd.Series] = {}

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "atr_period": {"type": "integer", "default": _DEFAULT_ATR_PERIOD},
                "risk_pct": {"type": "number", "default": _DEFAULT_RISK_PCT},
                "multiplier": {"type": "number", "default": _DEFAULT_MULTIPLIER},
            },
        }

    async def prepare(self, context: SizingContext) -> None:
        self._atr_period = int(context.params.get("atr_period", _DEFAULT_ATR_PERIOD))
        self._risk_pct = float(context.params.get("risk_pct", _DEFAULT_RISK_PCT))
        self._multiplier = float(context.params.get("multiplier", _DEFAULT_MULTIPLIER))

        ohlcv = await load_ohlcv(context.symbols, context.start_date, context.end_date)
        for symbol, df in ohlcv.items():
            self._atr[symbol] = compute_atr(
                df["high"], df["low"], df["close"], self._atr_period,
            )

        logger.info(
            f"AtrRisk prepared | period={self._atr_period} | risk_pct={self._risk_pct}"
        )

    def compute_weights(
        self,
        signals: dict[str, FusionResult],
        portfolio: PortfolioState,
        market_data: dict[str, pd.DataFrame] | None = None,
    ) -> dict[str, SizingResult]:
        if not signals:
            return {}

        risk_budget = portfolio.total_value * self._risk_pct
        raw_weights: dict[str, float] = {}

        for symbol in signals:
            atr = self._get_atr(symbol, portfolio.current_date)
            if atr > 0:
                # 风险预算 / (ATR × 倍数) = 目标仓位金额 / 总资产
                raw_weights[symbol] = risk_budget / (atr * self._multiplier * portfolio.total_value)
            else:
                raw_weights[symbol] = 0.0

        total = sum(raw_weights.values())
        if total > 1.0:
            raw_weights = {s: w / total for s, w in raw_weights.items()}

        return {
            symbol: SizingResult(
                symbol=symbol,
                target_weight=raw_weights[symbol],
                sizing_strategy=self.strategy_name,
                raw_score=raw_weights[symbol],
            )
            for symbol in signals
        }

    def _get_atr(self, symbol: str, current_date: Any) -> float:
        """获取指定日期的 ATR 值。"""
        atr_series = self._atr.get(symbol)
        if atr_series is None or atr_series.empty:
            return 0.0
        if current_date in atr_series.index:
            val = atr_series.loc[current_date]
            return float(val) if pd.notna(val) else 0.0
        valid = atr_series.dropna()
        return float(valid.iloc[-1]) if not valid.empty else 0.0
