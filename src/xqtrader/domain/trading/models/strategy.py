"""策略引擎 — 策略定义 & 规则组 & 规则绑定"""

from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase

from ..enums import CombinationMethod, GroupType, StrategyStatus


class Strategy(AuditedBase):
    """策略定义 — 截面选股 + 时序信号 + 配仓 + 风控覆盖的完整配置"""

    __bind_key__ = "trading"
    __tablename__ = "td_strategy"

    strategy_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, comment="策略编码",
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="策略名称")
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, default="", comment="策略说明",
    )
    cross_section_config: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default={}, comment="截面选股规则组配置",
    )
    time_series_config: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default={}, comment="时序信号规则组配置",
    )
    position_sizing_config: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default={}, comment="仓位管理配置",
    )
    risk_overrides: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default={}, comment="风控规则覆盖",
    )
    universe_pool: Mapped[str | None] = mapped_column(
        String(16), nullable=True, default="", comment="默认样本池",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=StrategyStatus.DRAFT,
        comment="状态: draft/active/deprecated",
    )

    __table_args__ = ({"comment": "策略定义"},)


class StrategyRuleGroup(AuditedBase):
    """策略规则组 — 每个策略包含截面规则组和时序规则组"""

    __bind_key__ = "trading"
    __tablename__ = "td_strategy_rule_group"

    strategy_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True, comment="策略定义ID",
    )
    group_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=GroupType.CROSS_SECTION,
        comment="组类型: cross_section/time_series",
    )
    combination_method: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CombinationMethod.AND,
        comment="组合方式: and/or/weighted_score/weighted_vote/ic_weighted",
    )
    combination_params: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default={}, comment="组合参数",
    )
    threshold: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="通过阈值",
    )

    __table_args__ = ({"comment": "策略规则组"},)


class StrategyRuleBinding(AuditedBase):
    """策略-规则绑定 — 规则组内各规则的权重与配置覆盖"""

    __bind_key__ = "trading"
    __tablename__ = "td_strategy_rule_binding"

    group_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True, comment="规则组ID",
    )
    rule_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="规则ID → td_rule_registry",
    )
    weight: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=1.0, comment="权重 0-1",
    )
    config_override: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default={}, comment="覆盖默认配置",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="排序",
    )

    __table_args__ = ({"comment": "策略-规则绑定"},)
