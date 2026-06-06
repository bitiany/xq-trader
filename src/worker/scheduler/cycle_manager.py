"""周期管理器 — 管理调度周期 ID 生成和状态。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, cast

from framework.commons.redis_client import redis_client


class CycleManager:
    def __init__(
        self,
        timezone_name: str = "Asia/Shanghai",
        cycle_ttl: int = 604800,
    ) -> None:
        self._tz_name = timezone_name
        self._cycle_ttl = cycle_ttl

    def _get_now(self) -> datetime:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(self._tz_name)
        return datetime.now(tz)

    def current_cycle_id(self, window: str | None = None) -> str:
        if window is None:
            window = "day"
        now = self._get_now()
        if window == "hour":
            return now.strftime("%Y-%m-%d-%H")
        elif window == "day":
            return now.strftime("%Y-%m-%d")
        elif window == "week":
            iso = now.isocalendar()
            return f"{iso[0]}-W{iso[1]:02d}"
        elif window == "month":
            return now.strftime("%Y-%m")
        else:
            raise ValueError(f"Unsupported cycle window: {window}")

    def set_cycle_status(self, cycle_id: str, status: str) -> None:
        key = f"cycle:{cycle_id}:status"
        redis_client.client.set(key, status, ex=self._cycle_ttl)  # type: ignore[attr-defined]

    def get_cycle_status(self, cycle_id: str) -> str | None:
        key = f"cycle:{cycle_id}:status"
        val = redis_client.client.get(key)  # type: ignore[attr-defined]
        if val is None:
            return None
        return val.decode() if isinstance(val, bytes) else str(val)

    def cleanup_expired_cycles(self, max_age_hours: int = 24) -> list[str]:
        now = self._get_now()
        cutoff = now - timedelta(hours=max_age_hours)
        expired: list[str] = []

        cursor: int = 0
        pattern = "cycle:*:status"
        while True:
            scan_result = redis_client.client.scan(cursor=cursor, match=pattern, count=100)  # type: ignore[attr-defined]
            result_tuple = cast(tuple[Any, list[Any]], scan_result)
            cursor = cast(int, result_tuple[0])
            keys = result_tuple[1]
            for key in keys:
                key_str = str(key)
                parts = key_str.split(":")
                if len(parts) < 3:
                    continue
                cycle_id = parts[1]
                status = redis_client.client.get(key_str)  # type: ignore[attr-defined]
                status_str = (
                    status.decode() if isinstance(status, bytes) else str(status) if status else None
                )
                if status_str in ("ACTIVE", None):
                    self._mark_timeout_if_stale(cycle_id, cutoff)
                    current_status = redis_client.client.get(key_str)  # type: ignore[attr-defined]
                    current_str = (
                        current_status.decode() if isinstance(current_status, bytes)
                        else str(current_status) if current_status else None
                    )
                    if current_str == "TIMEOUT":
                        expired.append(cycle_id)
            if cursor == 0:
                break

        return expired

    def _mark_timeout_if_stale(self, cycle_id: str, cutoff: datetime) -> None:
        try:
            cycle_date = self._parse_cycle_id(cycle_id)
            if cycle_date is not None and cycle_date < cutoff:
                self.set_cycle_status(cycle_id, "TIMEOUT")
        except Exception:
            pass

    def _parse_cycle_id(self, cycle_id: str) -> datetime | None:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(self._tz_name)
        for fmt in ("%Y-%m-%d-%H", "%Y-%m-%d", "%Y-%m"):
            try:
                return datetime.strptime(cycle_id, fmt).replace(tzinfo=tz)
            except ValueError:
                continue
        if cycle_id.startswith("20") and "-W" in cycle_id:
            try:
                parts = cycle_id.split("-W")
                year = int(parts[0])
                week = int(parts[1])
                jan4 = datetime(year, 1, 4, tzinfo=tz)
                start_of_week = jan4 - timedelta(days=jan4.weekday())
                return start_of_week + timedelta(weeks=week - 1)
            except (ValueError, IndexError):
                return None
        return None
