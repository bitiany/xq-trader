"""Cron 表达式解析工具 — 统一 cron 表达式解析逻辑。"""

from celery.schedules import crontab

from framework.commons.exceptions import InvalidCronExpressionError


def parse_cron(expr: str) -> dict[str, str]:
    """解析 5 字段 cron 表达式为 crontab 参数字典。

    Args:
        expr: 5 字段 cron 表达式，如 "0 8 * * 1-5"

    Returns:
        crontab 参数字典 {"minute", "hour", "day_of_month", "month_of_year", "day_of_week"}

    Raises:
        InvalidCronExpressionError: 表达式格式不正确
    """
    parts = expr.strip().split()
    if len(parts) != 5:
        raise InvalidCronExpressionError(f"Invalid cron expression (expected 5 fields): {expr}")
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day_of_month": parts[2],
        "month_of_year": parts[3],
        "day_of_week": parts[4],
    }


def parse_cron_to_crontab(expr: str) -> crontab:
    """解析 5 字段 cron 表达式为 Celery crontab 对象。

    Args:
        expr: 5 字段 cron 表达式

    Returns:
        crontab 实例

    Raises:
        InvalidCronExpressionError: 表达式格式不正确
    """
    params = parse_cron(expr)
    return crontab(**params)
