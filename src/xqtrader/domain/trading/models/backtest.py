"""回测运行记录 — 每次回测执行的输入参数 + 状态 + 绩效结果"""

from datetime import date, datetime

from sqlalchemy import DateTime, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase

from ..enums import BacktestRunStatus


class BacktestRun(AuditedBase):
    """回测运行记录 — 记录每次回测执行的入参（标的、日期、资金）和状态

    设计原则:
      - 策略配置（Strategy.config）描述"如何做"，与本表的运行参数解耦
      - 同一策略可多次运行，运行参数（symbols/日期/资金）由 API 入参注入
      - 不引用 selection_run_id：标的列表由调用方在 API 入参中直接传入
    """

    __bind_key__ = "trading"
    __tablename__ = "td_backtest_run"

    run_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, comment="回测运行唯一标识（UUID）",
    )
    strategy_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, comment="策略编码 → td_strategy.strategy_id",
    )
    symbols: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list,
        comment="回测标的列表（运行时入参，与策略配置解耦）",
    )
    start_date: Mapped[date] = mapped_column(nullable=False, comment="回测起始日期")
    end_date: Mapped[date] = mapped_column(nullable=False, comment="回测结束日期")
    initial_cash: Mapped[float] = mapped_column(
        Numeric(20, 4), nullable=False, comment="初始资金",
    )
    commission: Mapped[float] = mapped_column(
        Numeric(8, 6), nullable=False, default=0.0003, comment="手续费率",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=BacktestRunStatus.PENDING,
        comment="状态: pending/running/success/failed",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="开始执行时间",
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="完成时间",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="失败时的错误信息",
    )

    __table_args__ = ({"comment": "回测运行记录"},)


class BacktestResult(AuditedBase):
    """回测绩效结果 — 与 BacktestRun 一对一

    包含核心绩效指标、权益曲线、交易记录（JSONB 存储）。
    """

    __bind_key__ = "trading"
    __tablename__ = "td_backtest_result"

    run_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, comment="回测运行 ID → td_backtest_run.run_id",
    )
    metrics: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
        comment="绩效指标（total_return/sharpe/max_drawdown/win_rate 等）",
    )
    equity_curve: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list,
        comment="权益曲线（每日净值快照列表）",
    )
    trades: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list,
        comment="交易记录（含信号触发依据和因子值）",
    )

    __table_args__ = ({"comment": "回测绩效结果"},)
