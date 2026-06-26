"""时间工具 — 统一 Asia/Shanghai 时区。

A 股交易域所有"当前时间/日期"取值必须使用本模块，避免 UTC 与本地时间在
跨日边界（北京时间 0:00-8:00 = UTC 前一日 16:00-24:00）出现日期错位。
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

# A 股交易时区
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def now_shanghai() -> datetime:
    """返回带 Asia/Shanghai 时区的当前时间。"""
    return datetime.now(SHANGHAI_TZ)


def today_shanghai() -> date:
    """返回 Asia/Shanghai 时区的当前日期。"""
    return now_shanghai().date()
