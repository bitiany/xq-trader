from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from xqtrader.domain.watermark.models.trade_calendar import TradeCalendar


class TestTradeCalendar:
    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_next_trade_date_returns_first_open_day_after(self) -> None:
        after = date(2026, 7, 3)
        next_day = date(2026, 7, 6)
        row = SimpleNamespaceRow(cal_date=next_day)
        filter_mock = AsyncMock(return_value=[row])

        with patch.object(TradeCalendar, "filter", filter_mock):
            result = await TradeCalendar.get_next_trade_date(after)

        assert result == next_day
        filter_mock.assert_awaited_once()
        call_kwargs = filter_mock.await_args.kwargs
        assert call_kwargs["exchange"] == "SSE"
        assert call_kwargs["is_open"] is True
        assert call_kwargs["cal_date__gt"] == after
        assert call_kwargs["limit"] == 1

    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_next_trade_date_returns_none_when_missing(self) -> None:
        with patch.object(TradeCalendar, "filter", new_callable=AsyncMock, return_value=[]):
            result = await TradeCalendar.get_next_trade_date(date(2026, 12, 31))

        assert result is None


class SimpleNamespaceRow:
    def __init__(self, cal_date: date) -> None:
        self.cal_date = cal_date
