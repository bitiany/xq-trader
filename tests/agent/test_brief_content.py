"""投研简报内容判定单元测试。"""

from __future__ import annotations

from agent.brief_content import is_indexable_brief


def test_indexable_brief_requires_title_and_length() -> None:
    short = "投研简报（2026-07-06）\n" + "x" * 100
    assert not is_indexable_brief(short)

    long_enough = "投研简报（2026-07-06）\n" + "x" * 320
    assert is_indexable_brief(long_enough)


def test_indexable_brief_accepts_trading_section() -> None:
    content = "## 交易策略\n" + "- 方向: 观望\n" + "y" * 320
    assert is_indexable_brief(content)


def test_non_brief_content_rejected() -> None:
    assert not is_indexable_brief("ping")
