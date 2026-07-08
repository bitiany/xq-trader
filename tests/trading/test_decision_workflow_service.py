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

    def test_add_pre_order_uses_incremental_qty(self) -> None:
        item = {"target_qty": 3700, "current_qty": 1700}

        qty = WatchlistDecisionWorkflowService._build_pre_order_target_qty(item, PreOrderSide.ADD)

        assert qty == 2000

    def test_add_pre_order_skips_when_already_at_target(self) -> None:
        item = {"target_qty": 1700, "current_qty": 1700}

        qty = WatchlistDecisionWorkflowService._build_pre_order_target_qty(item, PreOrderSide.ADD)

        assert qty is None

    def test_should_skip_rebalance_when_weight_within_threshold(self) -> None:
        item = {
            "target_weight": 0.10,
            "current_weight": 0.092653,
            "target_qty": 100,
        }

        assert WatchlistDecisionWorkflowService._should_create_pre_order(item, PreOrderSide.ADD) is False

    def test_should_keep_close_signal_even_when_weight_near_zero(self) -> None:
        item = {
            "target_weight": 0.0,
            "current_weight": 0.057832,
            "target_qty": 600,
        }

        assert WatchlistDecisionWorkflowService._should_create_pre_order(item, PreOrderSide.CLOSE) is True

    def test_should_create_add_when_weight_deviation_exceeds_threshold(self) -> None:
        item = {
            "target_weight": 0.20,
            "current_weight": 0.09,
            "target_qty": 2000,
        }

        assert WatchlistDecisionWorkflowService._should_create_pre_order(item, PreOrderSide.ADD) is True

    def test_should_skip_reduce_when_weight_within_threshold(self) -> None:
        item = {
            "target_weight": 0.10,
            "current_weight": 0.092653,
            "target_qty": 200,
        }

        assert WatchlistDecisionWorkflowService._should_create_pre_order(item, PreOrderSide.REDUCE) is False

    def test_should_create_reduce_when_weight_deviation_exceeds_threshold(self) -> None:
        item = {
            "target_weight": 0.10,
            "current_weight": 0.20,
            "target_qty": 1000,
        }

        assert WatchlistDecisionWorkflowService._should_create_pre_order(item, PreOrderSide.REDUCE) is True

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

    def test_normalize_weight_removes_float_boundary_noise(self) -> None:
        assert WatchlistDecisionWorkflowService._normalize_weight(0.1 + 0.2) == 0.3

    @pytest.mark.asyncio(loop_scope="session")
    async def test_risk_gateway_allows_total_weight_at_float_precision_boundary(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        created_events: list[dict[str, Any]] = []

        class FakeRiskEvent:
            @classmethod
            async def create(cls, **kwargs: Any) -> None:
                created_events.append(kwargs)

            @classmethod
            async def filter(cls, **kwargs: Any) -> list[Any]:
                return []

        monkeypatch.setattr("xqtrader.domain.trading.workflow.service.RiskEvent", FakeRiskEvent)
        service = WatchlistDecisionWorkflowService()
        context = {
            "account_id": 11,
            "instance_id": 2,
            "account": {"reduce_only": False},
            "instance": {
                "position_sizing": {"max_total_weight": 0.2},
                "risk_overrides": {"max_total_weight": 0.2, "max_single_weight": 0.2},
            },
        }
        sizing_result = {
            "sizing_results": [
                {
                    "symbol": "600522.SH",
                    "direction": "long",
                    "target_weight": 0.05,
                    "current_weight": 0.0,
                    "target_qty": 700,
                },
                {
                    "symbol": "600206.SH",
                    "direction": "long",
                    "target_weight": 0.05,
                    "current_weight": 0.0,
                    "target_qty": 800,
                },
                {
                    "symbol": "300136.SZ",
                    "direction": "long",
                    "target_weight": 0.05,
                    "current_weight": 0.0,
                    "target_qty": 400,
                },
                {
                    "symbol": "300433.SZ",
                    "direction": "long",
                    "target_weight": 0.05,
                    "current_weight": 0.0,
                    "target_qty": 800,
                },
                {
                    "symbol": "002463.SZ",
                    "direction": "short",
                    "target_weight": 0.0,
                    "current_weight": 0.0,
                    "target_qty": None,
                },
            ],
        }

        result = await service.run_risk_gateway.__wrapped__(service, context, sizing_result)

        assert result["total_weight"] == 0.2
        assert len(result["approved"]) == 5
        assert result["rejected"] == []
        assert created_events == []

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


class TestPreOrderExecutionWorkflowService:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_approved_paper_pre_order_creates_and_submits_order(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from decimal import Decimal

        from xqtrader.domain.trading.enums import (
            AccountType,
            ApprovalStatus,
            BrokerType,
            OrderEventType,
            OrderSide,
            OrderStatus,
            OrderType,
            PreOrderSide,
            PreOrderStatus,
        )
        from xqtrader.domain.trading.workflow.execution_service import PreOrderExecutionWorkflowService
        from xqtrader.domain.trading.workflow.simulated_matching_service import SimulatedMatchingService

        class FakeModel:
            _store: dict[int, Any] = {}
            _next_id = 1

            def __init__(self, **kwargs: Any) -> None:
                self.id = kwargs.pop("id", None)
                self.created_at = None
                self.updated_at = None
                for key, value in kwargs.items():
                    setattr(self, key, value)

            @classmethod
            async def get(cls, id_: int) -> Any | None:
                return cls._store.get(id_)

            @classmethod
            async def get_one_or_none(cls, **filters: Any) -> Any | None:
                for item in cls._store.values():
                    if all(getattr(item, key) == value for key, value in filters.items()):
                        return item
                return None

            @classmethod
            async def create(cls, **kwargs: Any) -> Any:
                item = cls(**kwargs)
                item.id = cls._next_id
                cls._next_id += 1
                cls._store[item.id] = item
                return item

            async def update(self, data: dict[str, Any]) -> None:
                for key, value in data.items():
                    setattr(self, key, value)

            def to_dict(self) -> dict[str, Any]:
                return dict(self.__dict__)

            @classmethod
            async def filter(cls, limit: int | None = None, order_by: Any = None, **filters: Any) -> list[Any]:
                # 支持常见 lookup：`field__in=[...]`、`field__lt=value`；其余按等值匹配。
                items: list[Any] = []
                for item in cls._store.values():
                    matched = True
                    for key, value in filters.items():
                        if key.endswith("__in"):
                            field = key[:-4]
                            if getattr(item, field, None) not in value:
                                matched = False
                                break
                        elif key.endswith("__lt"):
                            field = key[:-4]
                            field_value = getattr(item, field, None)
                            if field_value is None or field_value >= value:
                                matched = False
                                break
                        else:
                            if getattr(item, key, None) != value:
                                matched = False
                                break
                    if matched:
                        items.append(item)
                if limit is not None:
                    items = items[:limit]
                return items

        class FakeAccount(FakeModel):
            _store: dict[int, Any] = {}
            _next_id = 1

        class FakeInstance(FakeModel):
            _store: dict[int, Any] = {}
            _next_id = 1

        class FakePreOrder(FakeModel):
            _store: dict[int, Any] = {}
            _next_id = 1

        class FakeOrder(FakeModel):
            _store: dict[int, Any] = {}
            _next_id = 1

        class FakeOrderEvent(FakeModel):
            _store: dict[int, Any] = {}
            _next_id = 1

        class FakeTrade(FakeModel):
            _store: dict[int, Any] = {}
            _next_id = 1

        class FakePositionSnapshot(FakeModel):
            _store: dict[int, Any] = {}
            _next_id = 1
            snapshot_date = type("OrderField", (), {"desc": staticmethod(lambda: None)})()

            @classmethod
            async def filter(cls, limit: int | None = None, order_by: Any = None, **filters: Any) -> list[Any]:
                items = [
                    item for item in cls._store.values()
                    if all(getattr(item, key) == value for key, value in filters.items())
                ]
                items.sort(key=lambda item: item.snapshot_date, reverse=True)
                return items[:limit] if limit is not None else items

        class FakeAccountSnapshot(FakeModel):
            _store: dict[int, Any] = {}
            _next_id = 1
            # 模拟 ORM 的 snapshot_date 排序字段（_load_previous_account_snapshot 使用）
            snapshot_date = type("OrderField", (), {"desc": staticmethod(lambda: None)})()

        account = FakeAccount(
            id=1,
            account_type=AccountType.PAPER,
            broker_type=BrokerType.SIMULATED,
            is_enabled=True,
            reduce_only=False,
            initial_capital=Decimal("100000"),
            available_cash=Decimal("100000"),
            frozen_cash=Decimal("0"),
        )
        instance = FakeInstance(
            id=11,
            account_id=account.id,
            started_at=None,
            stopped_at=None,
        )
        pre_order = FakePreOrder(
            id=21,
            instance_id=instance.id,
            workflow_run_id="decision-run",
            signal_date=date(2026, 6, 24),
            execution_date=date(2026, 6, 25),
            symbol="600000.SH",
            side=PreOrderSide.OPEN,
            target_weight=0.1,
            current_weight=0.0,
            target_qty=100,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("10.1200"),
            sizing_strategy="watchlist_target_weight",
            status=PreOrderStatus.APPROVED,
            risk_check_passed=True,
            risk_check_detail={"passed": True, "approval_execution": {"slippage": {"type": "none"}}},
            approval_status=ApprovalStatus.APPROVED,
            approved_at=None,
            expired_at=None,
        )
        FakeAccount._store[account.id] = account
        FakeInstance._store[instance.id] = instance
        FakePreOrder._store[pre_order.id] = pre_order

        monkeypatch.setattr("xqtrader.domain.trading.workflow.execution_service.TradingAccount", FakeAccount)
        monkeypatch.setattr("xqtrader.domain.trading.workflow.execution_service.StrategyInstance", FakeInstance)
        monkeypatch.setattr("xqtrader.domain.trading.workflow.execution_service.PreOrder", FakePreOrder)
        monkeypatch.setattr("xqtrader.domain.trading.workflow.execution_service.Order", FakeOrder)
        monkeypatch.setattr("xqtrader.domain.trading.workflow.execution_service.OrderEvent", FakeOrderEvent)
        # Trade/PositionSnapshot/AccountSnapshot 已移至 simulated_matching_service 模块，
        # execution_service 不再 import 这些类，无需 monkeypatch（下方 sim_mod 已覆盖）。
        # SimulatedMatchingService 直接引用 simulated_matching_service 模块中的 ORM 类，
        # 需同步 monkeypatch，否则 submit_simulated_order 会查询真实数据库。
        sim_mod = "xqtrader.domain.trading.workflow.simulated_matching_service"
        monkeypatch.setattr(f"{sim_mod}.TradingAccount", FakeAccount)
        monkeypatch.setattr(f"{sim_mod}.PreOrder", FakePreOrder)
        monkeypatch.setattr(f"{sim_mod}.Trade", FakeTrade)
        monkeypatch.setattr(f"{sim_mod}.PositionSnapshot", FakePositionSnapshot)
        monkeypatch.setattr(f"{sim_mod}.AccountSnapshot", FakeAccountSnapshot)

        service = PreOrderExecutionWorkflowService()
        matching_service = SimulatedMatchingService(service)
        context = await service.load_execution_context(pre_order.id)
        create_result = await service.create_order_from_pre_order.__wrapped__(
            service, context, "exec-run", "tester",
        )
        submit_result = await matching_service.submit_simulated_order.__wrapped__(
            matching_service, create_result["order"]["id"], "tester",
        )

        assert context["submitter"] == "simulated"
        assert create_result["order"]["side"] == OrderSide.BUY
        assert create_result["order"]["order_qty"] == 100
        assert submit_result["order"]["status"] == OrderStatus.FILLED
        assert submit_result["order"]["filled_qty"] == 100
        assert submit_result["order"]["filled_price"] == "10.1200"
        assert submit_result["trade"]["filled_qty"] == 100
        assert submit_result["trade"]["filled_amount"] == "1012.0000"
        assert submit_result["order"]["broker_order_id"].startswith("SIM-")
        assert getattr(pre_order, "status") == PreOrderStatus.SUBMITTED
        assert getattr(account, "available_cash") == Decimal("98987.6964")
        assert len(FakeTrade._store) == 1
        assert len(FakePositionSnapshot._store) == 1
        assert len(FakeAccountSnapshot._store) == 1
        position = next(iter(FakePositionSnapshot._store.values()))
        snapshot = next(iter(FakeAccountSnapshot._store.values()))
        assert position.qty == 100
        assert position.available_qty == 0
        assert position.weight == Decimal("0.010120")
        assert snapshot.total_assets == Decimal("99999.6964")
        assert [event.event_type for event in FakeOrderEvent._store.values()] == [
            OrderEventType.CREATED,
            OrderEventType.RISK_CHECKED,
            OrderEventType.SUBMITTED,
            OrderEventType.FILLED,
        ]

    @pytest.mark.asyncio(loop_scope="session")
    async def test_rejected_order_consumes_pre_order_after_qmt_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from decimal import Decimal

        from xqtrader.domain.trading.enums import (
            OrderStatus,
            OrderType,
            PreOrderSide,
            PreOrderStatus,
        )
        from xqtrader.domain.trading.workflow.execution_service import PreOrderExecutionWorkflowService

        class FakeModel:
            _store: dict[int, Any] = {}
            _next_id = 1

            def __init__(self, **kwargs: Any) -> None:
                self.id = kwargs.pop("id", None)
                self.created_at = None
                self.updated_at = None
                for key, value in kwargs.items():
                    setattr(self, key, value)

            @classmethod
            async def get(cls, id_: int) -> Any | None:
                return cls._store.get(id_)

            @classmethod
            async def create(cls, **kwargs: Any) -> Any:
                item = cls(**kwargs)
                item.id = cls._next_id
                cls._next_id += 1
                cls._store[item.id] = item
                return item

            async def update(self, data: dict[str, Any]) -> None:
                for key, value in data.items():
                    setattr(self, key, value)

            def to_dict(self) -> dict[str, Any]:
                return dict(self.__dict__)

        class FakeOrder(FakeModel):
            _store: dict[int, Any] = {}
            _next_id = 1

        class FakePreOrder(FakeModel):
            _store: dict[int, Any] = {}
            _next_id = 1

        class FakeOrderEvent(FakeModel):
            _store: dict[int, Any] = {}
            _next_id = 1

        # 预订单初始为 SUBMITTED（已提交），mark_order_rejected 后应回退到 APPROVED 允许重提。
        pre_order = FakePreOrder(id=31, status=PreOrderStatus.SUBMITTED)
        order = FakeOrder(
            id=41,
            account_id=1,
            platform_order_id="platform-41",
            pre_order_id=pre_order.id,
            status=OrderStatus.CREATED,
            order_qty=100,
            order_price=Decimal("10.1200"),
            order_type=OrderType.LIMIT,
            side=PreOrderSide.OPEN,
            symbol="600000.SH",
        )
        FakePreOrder._store[pre_order.id] = pre_order
        FakeOrder._store[order.id] = order
        monkeypatch.setattr("xqtrader.domain.trading.workflow.execution_service.PreOrder", FakePreOrder)
        monkeypatch.setattr("xqtrader.domain.trading.workflow.execution_service.Order", FakeOrder)
        monkeypatch.setattr("xqtrader.domain.trading.workflow.execution_service.OrderEvent", FakeOrderEvent)

        service = PreOrderExecutionWorkflowService()
        await service.mark_order_rejected.__wrapped__(service, order.id, "QMT 连接失败", "tester")

        assert getattr(order, "status") == OrderStatus.REJECTED
        assert getattr(pre_order, "status") == PreOrderStatus.APPROVED
