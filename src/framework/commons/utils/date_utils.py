"""
框架工具：日期解析工具
"""
from datetime import date, datetime
from typing import Any


def parse_date(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, float) and (val != val):
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    try:
        s = str(val).strip()
        if '.' in s:
            s = str(int(float(s)))
        if len(s) == 8:
            return datetime.strptime(s, '%Y%m%d').date()
        if len(s) == 10 and '-' in s:
            return datetime.strptime(s, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        pass
    return None


def parse_datetime(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, float) and (val != val):
        return None
    if isinstance(val, datetime):
        return val
    try:
        s = str(val).strip()
        if '.' in s:
            s = str(int(float(s)))
        if len(s) == 8:
            return datetime.strptime(s, '%Y%m%d')
        if len(s) == 10 and '-' in s:
            return datetime.strptime(s, '%Y%m-%d')
    except (ValueError, TypeError):
        pass
    return None
