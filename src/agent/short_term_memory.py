"""短期时序记忆 — 从会话历史提取近 N 个交易日的投研简报摘要。

用于 Harness ShortTermRecallHook，支撑日际快变量对比；非权威事实，今日决策仍以 spawn 为准。
所有 DB 查询经 PgSessionManager 后台事件循环执行，避免跨 loop 使用连接池。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from agent.session_backend import PgSessionManager
from xqtrader.domain.agent.models.session import AgentMessage
from xqtrader.domain.watermark.models.trade_calendar import (
    DEFAULT_TRADE_EXCHANGE,
    TradeCalendar,
)

_TZ = ZoneInfo("Asia/Shanghai")
_REPORT_DATE_RE = re.compile(
    r"投研简报[（(](\d{4}-\d{2}-\d{2})[）)]",
)
_CLOSE_RE = re.compile(r"收盘[价\s]*[:：]?\s*([0-9]+(?:\.[0-9]+)?)")
_DIRECTION_RE = re.compile(
    r"(?:^|\n)\s*[-*]?\s*方向\s*[:：]\s*([^\n]+)",
    re.MULTILINE,
)
_MIN_BRIEF_CHARS = 300


@dataclass(frozen=True, slots=True)
class BriefSnapshot:
    """单个交易日的简报摘要（从会话历史解析）。"""

    trade_date: date
    lag_trading_days: int
    decay_weight: float
    trade_direction: str | None
    close_price: str | None


class ShortTermMemoryService:
    """短期时序记忆服务 — 经 PgSessionManager 桥接查询会话历史。"""

    def __init__(self, session_manager: PgSessionManager) -> None:
        self._sessions = session_manager

    @staticmethod
    def decay_weight(lag_trading_days: int, *, half_life: float) -> float:
        if lag_trading_days <= 0:
            return 1.0
        if half_life <= 0:
            raise ValueError("half_life must be positive")
        return math.exp(-math.log(2) * lag_trading_days / half_life)

    @staticmethod
    def extract_report_date(content: str) -> date | None:
        match = _REPORT_DATE_RE.search(content)
        if not match:
            return None
        try:
            return date.fromisoformat(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def extract_trade_direction(content: str) -> str | None:
        match = _DIRECTION_RE.search(content)
        if not match:
            return None
        text = match.group(1).strip()
        return text[:80] if text else None

    @staticmethod
    def extract_close_price(content: str) -> str | None:
        match = _CLOSE_RE.search(content)
        if not match:
            return None
        return match.group(1)

    @staticmethod
    def resolve_session_key(session_key: str, symbol: str | None) -> str | None:
        """优先使用 stock:{symbol} 会话（与个股页一致），否则回退当前 session_key。"""
        if symbol:
            stock_key = f"stock:{symbol}"
            if session_key == stock_key or session_key.startswith("stock:"):
                return session_key
            return stock_key
        if session_key.startswith("stock:"):
            return session_key
        return None

    def load_recent_briefs(
        self,
        session_key: str,
        *,
        trading_days: int,
        half_life: float,
        max_entries: int = 3,
    ) -> list[BriefSnapshot]:
        if trading_days <= 0 or not session_key:
            return []

        trading_day_list = self._sessions.run_coroutine(
            _recent_trading_days(trading_days + 1),
        )
        if len(trading_day_list) < 2:
            return []

        prior_days = [d for d in trading_day_list[1 : trading_days + 1]]
        if not prior_days:
            return []

        oldest = min(prior_days)
        cutoff = datetime.combine(oldest, datetime.min.time(), tzinfo=_TZ).astimezone(
            timezone.utc,
        )
        rows = self._sessions.run_coroutine(
            _load_assistant_payloads_since(session_key, cutoff),
        )

        day_to_content: dict[date, str] = {}
        for payload in rows:
            content = (payload.get("content") or "").strip()
            if len(content) < _MIN_BRIEF_CHARS:
                continue
            if "投研简报" not in content and "## 交易策略" not in content:
                continue
            report_date = self.extract_report_date(content)
            if report_date is None:
                continue
            if report_date not in prior_days:
                continue
            if report_date not in day_to_content or len(content) > len(day_to_content[report_date]):
                day_to_content[report_date] = content

        lag_by_day = {d: i + 1 for i, d in enumerate(prior_days)}
        snapshots: list[BriefSnapshot] = []
        for td in prior_days:
            content = day_to_content.get(td)
            if not content:
                continue
            trading_lag = lag_by_day[td]
            snapshots.append(
                BriefSnapshot(
                    trade_date=td,
                    lag_trading_days=trading_lag,
                    decay_weight=round(
                        self.decay_weight(trading_lag, half_life=half_life),
                        2,
                    ),
                    trade_direction=self.extract_trade_direction(content),
                    close_price=self.extract_close_price(content),
                ),
            )
        return snapshots[:max_entries]

    @staticmethod
    def format_note(
        snapshots: list[BriefSnapshot],
        *,
        trading_days: int,
        half_life: float,
        unavailable: bool = False,
    ) -> str | None:
        if unavailable:
            return (
                "[短期时序记忆（不可用）]\n"
                "历史简报加载失败，今日分析须完全依赖实时 spawn 与论点卡；"
                "日际变化节标注「历史记忆不可用」。"
            )
        if not snapshots:
            return None
        lines = [
            f"[短期时序记忆（近 {trading_days} 个交易日·非权威参照）]",
            "以下摘自历史会话投研简报，仅供日际变化对比；今日快变量须重新 spawn，不得复用旧结论。",
            f"衰减半衰期={half_life} 交易日（权重随时间递减）。",
            "",
        ]
        for snap in snapshots:
            parts = [
                f"- {snap.trade_date}（lag={snap.lag_trading_days}d, w={snap.decay_weight}）",
            ]
            if snap.close_price:
                parts.append(f"收盘 {snap.close_price}")
            if snap.trade_direction:
                parts.append(f"建议 {snap.trade_direction}")
            lines.append(" | ".join(parts))
        lines.append("")
        lines.append("须在报告中输出「日际变化」节，说明建议/技术信号相对上述记忆的演变及原因。")
        return "\n".join(lines)


async def _recent_trading_days(
    count: int,
    *,
    exchange: str = DEFAULT_TRADE_EXCHANGE,
) -> list[date]:
    ref = await TradeCalendar.get_latest_trade_date(exchange=exchange)
    if ref is None:
        return []
    rows = await TradeCalendar.filter(
        exchange=exchange,
        is_open=True,
        cal_date__lte=ref,
        order_by=TradeCalendar.cal_date.desc(),
        limit=count,
    )
    return [row.cal_date for row in rows]


async def _load_assistant_payloads_since(
    session_key: str,
    cutoff: datetime,
) -> list[dict]:
    rows = await AgentMessage.filter(
        session_key=session_key,
        created_at__gte=cutoff,
        order_by=AgentMessage.seq,
    )
    return [
        row.payload
        for row in rows
        if (row.payload or {}).get("role") == "assistant"
    ]

