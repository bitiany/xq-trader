"""投研简报内容判定 — 短期记忆提取与 Qdrant 索引共用标准。"""

from __future__ import annotations

MIN_BRIEF_CHARS = 300


def is_indexable_brief(content: str) -> bool:
    """内容是否达到可索引/可提取的投研简报质量门槛。"""
    text = content.strip()
    if len(text) < MIN_BRIEF_CHARS:
        return False
    return "投研简报" in text or "## 交易策略" in text
