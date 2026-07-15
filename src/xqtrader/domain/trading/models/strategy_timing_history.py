"""策略择时历史 — 记录每次 strategy-timing 的信号与后续走势比对结果

设计原则:
  - 每次调用 strategy-timing 写入一条记录，包含 symbol/as_of/signals/decision/confidence
  - 后续走势比对时回填 outcome 字段（actual_return/verdict）
  - verdict 与 signal 比对计算策略胜率，反哺聚合权重
  - 样本数 >= 30 时启用权重反哺，避免小样本噪声
"""

from datetime import date

from sqlalchemy import Date, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase


class StrategyTimingHistory(AuditedBase):
    """策略择时历史 — 记录每次择时信号与后续走势比对

    表名: td_strategy_timing_history
    数据源: trading
    """

    __bind_key__ = "trading"
    __tablename__ = "td_strategy_timing_history"

    symbol: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        comment="标的代码，如 002049.SZ",
    )
    as_of: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        comment="择时日期",
    )
    market_regime: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="市场状态推断: trending_up/trending_down/sideways/volatile",
    )
    signals: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="各策略信号列表 [{rule_id, signal, confidence, weight, key_reason}]",
    )
    aggregated_signal: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="综合聚合信号: buy/hold/sell",
    )
    confidence: Mapped[float] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        comment="综合置信度 0.000-1.000",
    )
    decision_rationale: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="AI 综合聚合决策理由",
    )

    # ── 后续走势比对（回填） ──────────────────────────────────────────────
    actual_return: Mapped[float | None] = mapped_column(
        Numeric(8, 4),
        nullable=True,
        comment="比对窗口内实际收益率%（回填）",
    )
    verdict: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        comment="走势判定: win/loss/neutral（回填，与 aggregated_signal 比对）",
    )
    compared_at: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        comment="走势比对日期（回填）",
    )
    compare_window_days: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="比对窗口天数（默认 5 个交易日）",
    )

    __table_args__ = ({"comment": "策略择时历史 — 记录信号与后续走势比对"},)
