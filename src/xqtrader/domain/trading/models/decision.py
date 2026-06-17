"""决策流模型 — 选股 → 信号 → 融合 → 配仓"""

from datetime import date

from sqlalchemy import Date, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase

from ..enums import Direction


class SelectionResult(AuditedBase):
    """截面选股结果 — 决策流第一步输出"""

    __bind_key__ = "trading"
    __tablename__ = "td_selection_result"

    instance_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="策略实例ID")
    workflow_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="决策流 Run ID")
    signal_date: Mapped[date] = mapped_column(Date, nullable=False, comment="信号日")
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, comment="证券代码")
    score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="综合得分")
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="排名")
    factor_values: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default={}, comment="因子值快照")
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="工作流节点ID")

    __table_args__ = ({"comment": "截面选股结果"},)


class TradingSignal(AuditedBase):
    """逐标的交易信号 — 决策流第二步输出"""

    __bind_key__ = "trading"
    __tablename__ = "td_trading_signal"

    instance_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="策略实例ID")
    workflow_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="决策流 Run ID")
    signal_date: Mapped[date] = mapped_column(Date, nullable=False, comment="信号日")
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, comment="证券代码")
    direction: Mapped[str] = mapped_column(
        String(8), nullable=False, default=Direction.NEUTRAL, comment="方向: long/short/neutral",
    )
    strength: Mapped[float | None] = mapped_column(Float, nullable=True, comment="信号强度 0-1")
    signal_type: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="信号来源类型")
    raw_values: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default={}, comment="原始因子值")
    selection_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="选股结果ID")
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="工作流节点ID")

    __table_args__ = ({"comment": "交易信号"},)


class SignalFusionResult(AuditedBase):
    """信号融合结果 — 决策流第三步输出"""

    __bind_key__ = "trading"
    __tablename__ = "td_signal_fusion_result"

    instance_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="策略实例ID")
    workflow_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="决策流 Run ID")
    signal_date: Mapped[date] = mapped_column(Date, nullable=False, comment="信号日")
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, comment="证券代码")
    direction: Mapped[str] = mapped_column(
        String(8), nullable=False, default=Direction.NEUTRAL, comment="方向: long/short/neutral",
    )
    fused_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="融合得分")
    contributing_signals: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default={}, comment="贡献信号明细")
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="工作流节点ID")

    __table_args__ = ({"comment": "信号融合结果"},)


class PositionSizingResult(AuditedBase):
    """仓位管理输出 — 决策流第四步输出，直接驱动 pre_order"""

    __bind_key__ = "trading"
    __tablename__ = "td_position_sizing_result"

    instance_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="策略实例ID")
    workflow_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="决策流 Run ID")
    signal_date: Mapped[date] = mapped_column(Date, nullable=False, comment="信号日")
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, comment="证券代码")
    target_weight: Mapped[float | None] = mapped_column(Float, nullable=True, comment="目标权重 0-1")
    target_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="目标股数(100整数倍)")
    current_weight: Mapped[float | None] = mapped_column(Float, nullable=True, comment="当前权重")
    sizing_strategy: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="配仓策略ID")
    sizing_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default={}, comment="策略参数快照")
    raw_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="策略中间量")
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="工作流节点ID")

    __table_args__ = ({"comment": "仓位管理输出"},)
