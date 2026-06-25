from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from xqtrader.domain.trading.backtest.core import RuleContext
from xqtrader.domain.trading.backtest.plugins.donchian_turtle import DonchianTurtlePlugin
from xqtrader.domain.trading.enums import PreOrderSide
from xqtrader.domain.trading.workflow.service import WatchlistDecisionWorkflowService


class Bar:
    def __init__(self, high: float, low: float, close: float) -> None:
        self.high = high
        self.low = low
        self.close = close


class TestWatchlistDecisionWorkflowService:
    def test_empty_position_short_signal_has_no_pre_order_side(self) -> None:
        item = {"target_weight": 0.0, "current_weight": 0.0, "current_qty": 0}

        side = WatchlistDecisionWorkflowService._build_pre_order_side(item)

        assert side is None

    def test_existing_position_short_signal_closes_position(self) -> None:
        item = {"target_weight": 0.0, "current_weight": 0.12, "current_qty": 1000}

        side = WatchlistDecisionWorkflowService._build_pre_order_side(item)

        assert side == PreOrderSide.CLOSE

    def test_long_signal_uses_open_or_add_by_current_position(self) -> None:
        open_item = {"target_weight": 0.1, "current_weight": 0.0, "current_qty": 0}
        add_item = {"target_weight": 0.2, "current_weight": 0.1, "current_qty": 1000}

        assert WatchlistDecisionWorkflowService._build_pre_order_side(open_item) == PreOrderSide.OPEN
        assert WatchlistDecisionWorkflowService._build_pre_order_side(add_item) == PreOrderSide.ADD

    def test_lower_target_weight_reduces_existing_position(self) -> None:
        item = {"target_weight": 0.1, "current_weight": 0.2, "current_qty": 2000, "target_qty": 1000}

        side = WatchlistDecisionWorkflowService._build_pre_order_side(item)
        qty = WatchlistDecisionWorkflowService._build_pre_order_target_qty(item, side or "")

        assert side == PreOrderSide.REDUCE
        assert qty == 1000

    def test_close_pre_order_uses_current_available_qty(self) -> None:
        item = {"target_qty": None, "current_qty": 1000, "available_qty": 800}

        qty = WatchlistDecisionWorkflowService._build_pre_order_target_qty(item, PreOrderSide.CLOSE)

        assert qty == 800

    def test_calculate_atr_uses_true_range(self) -> None:
        bars = [
            Bar(high=10.0, low=9.0, close=9.5),
            Bar(high=11.0, low=9.2, close=10.2),
            Bar(high=10.5, low=9.5, close=10.0),
        ]

        atr = WatchlistDecisionWorkflowService._calculate_atr(bars)  # type: ignore[arg-type]

        assert atr == pytest.approx(1.4)

    def test_market_factor_values_build_donchian_channel(self) -> None:
        bars = [
            Bar(high=10.0, low=9.0, close=9.5),
            Bar(high=11.0, low=9.2, close=10.2),
            Bar(high=10.5, low=8.8, close=10.0),
        ]

        values = WatchlistDecisionWorkflowService._build_market_factor_values(bars)  # type: ignore[arg-type]

        assert values["close"] == 10.0
        assert values["donchian_high_20"] == 11.0
        assert values["donchian_low_10"] == 9.0
        assert values["atr_14"] == pytest.approx(1.75)

    def test_donchian_turtle_plugin_generates_breakout_buy_signal(self) -> None:
        result = DonchianTurtlePlugin().evaluate(RuleContext(
            symbol="600522.SH",
            signal_date=date(2026, 6, 24),
            factor_values={
                "close": 11.2,
                "donchian_high_20": 11.0,
                "donchian_low_10": 9.0,
                "atr_14": 1.0,
            },
        ))

        assert result.passed is True
        assert result.direction == "buy"
        assert result.confidence >= 0.72

    def test_donchian_turtle_plugin_generates_exit_sell_signal(self) -> None:
        result = DonchianTurtlePlugin().evaluate(RuleContext(
            symbol="600522.SH",
            signal_date=date(2026, 6, 24),
            factor_values={
                "close": 8.8,
                "donchian_high_20": 11.0,
                "donchian_low_10": 9.0,
                "atr_14": 1.0,
            },
        ))

        assert result.passed is True
        assert result.direction == "sell"
        assert result.confidence == pytest.approx(0.78)

    def test_portfolio_fusion_keeps_one_signal_per_symbol(self) -> None:
        signals = [
            {
                "symbol": "600522.SH",
                "direction": "long",
                "confidence": 0.8,
                "score": 0.7,
                "fusion_weight": 1.0,
            },
            {
                "symbol": "600522.SH",
                "direction": "short",
                "confidence": 0.7,
                "score": 0.5,
                "fusion_weight": 1.0,
            },
        ]
        candidates = [
            signal | {"fused_score": WatchlistDecisionWorkflowService._fused_score(signal)}
            for signal in signals
        ]

        selected = WatchlistDecisionWorkflowService._select_portfolio_signals(candidates, max_selected=10)

        assert len(selected) == 1
        assert selected[0]["direction"] == "long"

    def test_watchlist_weight_percent_converts_to_fraction(self) -> None:
        assert WatchlistDecisionWorkflowService._watchlist_weight_to_fraction(10) == pytest.approx(0.1)
        assert WatchlistDecisionWorkflowService._watchlist_weight_to_fraction(0.1) == pytest.approx(0.1)
        assert WatchlistDecisionWorkflowService._watchlist_weight_to_fraction(None) is None

    def test_watchlist_target_weight_requires_configured_weight(self) -> None:
        selected = [{"symbol": "600522.SH", "target_weight": None}]

        with pytest.raises(Exception, match="自选股目标权重未配置"):
            WatchlistDecisionWorkflowService._build_target_weights(
                selected,
                mode="watchlist_target_weight",
                max_total_weight=1.0,
            )

    def test_watchlist_target_weight_scales_total_weight(self) -> None:
        selected = [
            {"symbol": "600522.SH", "target_weight": 0.6},
            {"symbol": "300433.SZ", "target_weight": 0.6},
        ]

        weights = WatchlistDecisionWorkflowService._build_target_weights(
            selected,
            mode="watchlist_target_weight",
            max_total_weight=1.0,
        )

        assert sum(weights.values()) == pytest.approx(1.0)
        assert weights["600522.SH"] == pytest.approx(0.5)
        assert weights["300433.SZ"] == pytest.approx(0.5)

    def test_target_weight_respects_single_symbol_limit_before_scaling(self) -> None:
        selected = [
            {"symbol": "600522.SH", "target_weight": 0.6},
            {"symbol": "300433.SZ", "target_weight": 0.2},
        ]

        weights = WatchlistDecisionWorkflowService._build_target_weights(
            selected,
            mode="watchlist_target_weight",
            max_total_weight=1.0,
            max_single_weight=0.2,
        )

        assert weights == {"600522.SH": pytest.approx(0.2), "300433.SZ": pytest.approx(0.2)}

    def test_confidence_weighted_respects_single_symbol_limit(self) -> None:
        selected = [
            {"symbol": "600522.SH", "confidence": 0.9},
            {"symbol": "300433.SZ", "confidence": 0.1},
        ]

        weights = WatchlistDecisionWorkflowService._build_target_weights(
            selected,
            mode="confidence_weighted",
            max_total_weight=1.0,
            max_single_weight=0.2,
        )

        assert weights["600522.SH"] == pytest.approx(0.2)
        assert weights["300433.SZ"] == pytest.approx(0.1)

    def test_equal_weight_respects_single_symbol_limit(self) -> None:
        selected = [{"symbol": "600522.SH"}, {"symbol": "300433.SZ"}]

        weights = WatchlistDecisionWorkflowService._build_target_weights(
            selected,
            mode="equal_weight",
            max_total_weight=1.0,
            max_single_weight=0.2,
        )

        assert weights == {"600522.SH": pytest.approx(0.2), "300433.SZ": pytest.approx(0.2)}

    def test_calculate_target_qty_caps_new_buy_by_available_cash(self) -> None:
        qty = WatchlistDecisionWorkflowService._calculate_target_qty(
            total_assets=100000.0,
            available_cash=20000.0,
            target_weight=0.8,
            current_weight=0.0,
            market_price=10.0,
        )

        assert qty == 2000

    @pytest.mark.asyncio(loop_scope="session")
    async def test_multiple_long_signals_share_available_cash_budget(self) -> None:
        service = WatchlistDecisionWorkflowService()
        context = {
            "instance_id": 1,
            "signal_date": "2026-06-24",
            "account_snapshot": {"total_assets": 100000.0, "available_cash": 30000.0},
            "positions": {},
        }
        selected = [
            {"symbol": "600522.SH", "direction": "long", "fused_score": 0.9},
            {"symbol": "300433.SZ", "direction": "long", "fused_score": 0.8},
        ]

        async def load_close_price(symbol: str, signal_date: date) -> float:
            return 10.0

        service._load_close_price = load_close_price  # type: ignore[method-assign]
        result = await service._calculate_position_sizing_results(
            context=context,
            selected=selected,
            weights={"600522.SH": 0.5, "300433.SZ": 0.5},
            mode="equal_weight",
            signal_date=date(2026, 6, 24),
        )

        assert sum((item["target_qty"] or 0) * item["market_price"] for item in result) <= 30000.0
        assert [item["target_qty"] for item in result] == [3000, None]

    @pytest.mark.asyncio(loop_scope="session")
    async def test_short_signal_does_not_consume_long_position_budget(self) -> None:
        service = WatchlistDecisionWorkflowService()
        context = {
            "instance_id": 1,
            "signal_date": "2026-06-24",
            "instance": {
                "position_sizing": {"mode": "watchlist_target_weight", "max_total_weight": 1.0},
                "risk_overrides": {"max_single_weight": 1.0},
            },
            "account_snapshot": {"total_assets": 100000.0},
            "positions": {},
        }
        fusion_result = {
            "selected_signals": [
                {"symbol": "600522.SH", "direction": "long", "target_weight": 0.8, "fused_score": 0.9},
                {"symbol": "300433.SZ", "direction": "short", "target_weight": 0.8, "fused_score": 0.8},
            ],
        }

        async def load_close_price(symbol: str, signal_date: date) -> float:
            return 10.0

        service._load_close_price = load_close_price  # type: ignore[method-assign]
        weights = WatchlistDecisionWorkflowService._build_target_weights(
            [signal for signal in fusion_result["selected_signals"] if signal["direction"] != "short"],
            mode="watchlist_target_weight",
            max_total_weight=1.0,
            max_single_weight=1.0,
        )
        result = await service._calculate_position_sizing_results(
            context=context,
            selected=fusion_result["selected_signals"],
            weights=weights,
            mode="watchlist_target_weight",
            signal_date=date(2026, 6, 24),
        )

        by_symbol = {item["symbol"]: item for item in result}
        assert by_symbol["600522.SH"]["target_weight"] == pytest.approx(0.8)
        assert by_symbol["300433.SZ"]["target_weight"] == pytest.approx(0.0)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_build_entry_limit_price_uses_atr_buffer_for_open(self) -> None:
        class Service(WatchlistDecisionWorkflowService):
            async def _load_entry_quote(self, symbol: str, signal_date: date) -> dict[str, Any]:
                return {
                    "close": 10.0,
                    "bars": [
                        Bar(high=10.0, low=9.5, close=9.8),
                        Bar(high=10.4, low=9.6, close=10.0),
                    ],
                }

        item: dict[str, Any] = {"symbol": "600522.SH", "target_weight": 0.1, "current_weight": 0.0, "current_qty": 0}

        price = await Service()._build_entry_limit_price(item, signal_date=date(2026, 6, 24))

        assert price is not None
        assert float(price) == pytest.approx(10.16)
        assert item["entry_price_detail"]["method"] == "atr_limit_buffer"
        assert item["entry_price_detail"]["side"] == PreOrderSide.OPEN
