"""信号融合引擎 — 截面选股 × 时序信号 → 最终交易信号。

融合规则（参考 docs/rule-strategy-design.md §7 信号融合表）:
  截面入选 + 时序 long   → long,   score = cs_score × ts_strength
  截面入选 + 时序 neutral → long,   score = cs_score × 0.5（持有）
  截面入选 + 时序 short  → neutral, score = 0（过滤空头）
  截面未入选 + 时序 long  → neutral, score = 0（过滤未入选）
  截面未入选 + 时序 short → short,  score = ts_strength
  截面未入选 + 时序 neutral → neutral, score = 0

当无截面选股结果时（纯时序回测），直接使用时序信号。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.commons.logger import get_logger

from ..rules.base import SelectionScore
from .engine import SignalResult

logger = get_logger(__name__)


@dataclass
class FusionResult:
    """信号融合结果 — 截面×时序融合后的最终信号。"""

    symbol: str
    direction: str = "neutral"
    fused_score: float = 0.0
    contributing_signals: dict[str, Any] = field(default_factory=dict)


class SignalFusionEngine:
    """信号融合引擎 — 环境无关，纯计算。

    用法:
        engine = SignalFusionEngine()
        results = engine.fuse(selection_scores, signal_results)
    """

    @staticmethod
    def fuse(
        selection: dict[str, SelectionScore] | None,
        signals: dict[str, SignalResult],
    ) -> dict[str, FusionResult]:
        """融合截面选股与时序信号。

        Args:
            selection: 截面选股结果 {symbol: SelectionScore}，None 表示无截面选股
            signals: 时序信号结果 {symbol: SignalResult}

        Returns:
            {symbol: FusionResult} 融合后的最终信号
        """
        if selection is None:
            return SignalFusionEngine._fuse_signals_only(signals)
        return SignalFusionEngine._fuse_with_selection(selection, signals)

    @staticmethod
    def _fuse_signals_only(signals: dict[str, SignalResult]) -> dict[str, FusionResult]:
        """纯时序模式 — 无截面选股时直接使用时序信号。"""
        results: dict[str, FusionResult] = {}
        for symbol, signal in signals.items():
            results[symbol] = FusionResult(
                symbol=symbol,
                direction=signal.direction,
                fused_score=signal.strength,
                contributing_signals={
                    "ts_direction": signal.direction,
                    "ts_strength": signal.strength,
                    "source": "time_series_only",
                },
            )
        return results

    @staticmethod
    def _fuse_with_selection(
        selection: dict[str, SelectionScore],
        signals: dict[str, SignalResult],
    ) -> dict[str, FusionResult]:
        """截面×时序融合模式。"""
        results: dict[str, FusionResult] = {}
        all_symbols = set(selection.keys()) | set(signals.keys())

        for symbol in all_symbols:
            cs = selection.get(symbol)
            ts = signals.get(symbol)
            cs_selected = cs is not None
            cs_score = cs.score if cs else 0.0
            ts_direction = ts.direction if ts else "neutral"
            ts_strength = ts.strength if ts else 0.0

            direction, fused_score = SignalFusionEngine._apply_fusion_rule(
                cs_selected, cs_score, ts_direction, ts_strength,
            )

            results[symbol] = FusionResult(
                symbol=symbol,
                direction=direction,
                fused_score=fused_score,
                contributing_signals={
                    "cs_selected": cs_selected,
                    "cs_score": cs_score,
                    "ts_direction": ts_direction,
                    "ts_strength": ts_strength,
                    "source": "fusion",
                },
            )
        return results

    @staticmethod
    def _apply_fusion_rule(
        cs_selected: bool,
        cs_score: float,
        ts_direction: str,
        ts_strength: float,
    ) -> tuple[str, float]:
        """应用单标的融合规则，返回 (direction, fused_score)。"""
        if cs_selected:
            if ts_direction == "long":
                return "long", cs_score * ts_strength
            if ts_direction == "neutral":
                return "long", cs_score * 0.5
            # ts_direction == "short"
            return "neutral", 0.0

        # 截面未入选
        if ts_direction == "short":
            return "short", ts_strength
        return "neutral", 0.0
