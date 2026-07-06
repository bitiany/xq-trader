"""短期时序记忆单元测试。"""

from __future__ import annotations

from datetime import date

from agent.short_term_memory import BriefSnapshot, ShortTermMemoryService


def test_decay_weight_half_life() -> None:
    assert ShortTermMemoryService.decay_weight(0, half_life=1.5) == 1.0
    assert round(ShortTermMemoryService.decay_weight(1, half_life=1.5), 2) == 0.63
    assert round(ShortTermMemoryService.decay_weight(2, half_life=1.5), 2) == 0.40
    assert round(ShortTermMemoryService.decay_weight(3, half_life=1.5), 2) == 0.25


def test_extract_report_date() -> None:
    content = "# 603993.SH 洛阳钼业 投研简报（2026-07-06）\n"
    assert ShortTermMemoryService.extract_report_date(content) == date(2026, 7, 6)


def test_extract_trade_direction() -> None:
    content = "## 交易策略\n- 方向: 观望（等待企稳）\n"
    assert ShortTermMemoryService.extract_trade_direction(content) == "观望（等待企稳）"


def test_extract_close_price() -> None:
    content = "## 最新行情\n- 收盘价: 18.31（-1.13%）\n"
    assert ShortTermMemoryService.extract_close_price(content) == "18.31"


def test_format_short_term_note() -> None:
    snaps = [
        BriefSnapshot(
            trade_date=date(2026, 7, 6),
            lag_trading_days=1,
            decay_weight=0.63,
            trade_direction="观望",
            close_price="18.31",
        ),
    ]
    note = ShortTermMemoryService.format_note(snaps, trading_days=3, half_life=1.5)
    assert note is not None
    assert "短期时序记忆" in note
    assert "2026-07-06" in note
    assert "观望" in note


def test_resolve_session_key_prefers_stock_symbol() -> None:
    assert (
        ShortTermMemoryService.resolve_session_key("session:abc", "603993.SH")
        == "stock:603993.SH"
    )
    assert (
        ShortTermMemoryService.resolve_session_key("stock:603993.SH", "603993.SH")
        == "stock:603993.SH"
    )


def test_format_unavailable_note() -> None:
    note = ShortTermMemoryService.format_note(
        [],
        trading_days=3,
        half_life=1.5,
        unavailable=True,
    )
    assert note is not None
    assert "不可用" in note
