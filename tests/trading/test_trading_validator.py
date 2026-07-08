from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from framework.commons.exceptions import BusinessException
from xqtrader.domain.trading.enums import (
    AccountType,
    ApprovalStatus,
    BrokerType,
    OrderType,
    PreOrderSide,
    PreOrderStatus,
)
from xqtrader.domain.trading.workflow.trading_validator import TradingValidator


def _build_pre_order(**overrides: object) -> SimpleNamespace:
    defaults = {
        "id": 1,
        "approval_status": ApprovalStatus.APPROVED,
        "status": PreOrderStatus.APPROVED,
        "risk_check_passed": True,
        "target_qty": 100,
        "order_type": OrderType.MARKET,
        "limit_price": None,
        "side": PreOrderSide.ADD,
        "execution_date": date.today(),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _build_account(**overrides: object) -> SimpleNamespace:
    defaults = {
        "id": 1,
        "is_enabled": True,
        "account_type": AccountType.PAPER,
        "broker_type": BrokerType.SIMULATED,
        "reduce_only": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestTradingValidator:
    def test_rejects_pre_order_before_execution_date(self) -> None:
        pre_order = _build_pre_order(execution_date=date.today() + timedelta(days=1))
        account = _build_account()

        with patch("xqtrader.domain.trading.workflow.trading_validator.today_shanghai", return_value=date.today()):
            with pytest.raises(BusinessException, match="未到执行日"):
                TradingValidator.validate_pre_order(pre_order, account)  # type: ignore[arg-type]

    def test_allows_pre_order_on_execution_date(self) -> None:
        pre_order = _build_pre_order(execution_date=date.today())
        account = _build_account()

        with patch("xqtrader.domain.trading.workflow.trading_validator.today_shanghai", return_value=date.today()):
            TradingValidator.validate_pre_order(pre_order, account)  # type: ignore[arg-type]
