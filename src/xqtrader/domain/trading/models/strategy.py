"""策略定义 — 单表 JSONB 配置

设计原则:
  - 配置层 (Strategy.config) 描述"如何做"，与具体股票、日期、资金无关
  - 运行时参数 (symbols/start_date/end_date/cash) 由 API 入参注入
  - 截面选股 (strategy_type=selection) 与时序回测 (strategy_type=timing) 完全独立
  - 规则组 + 组间融合内嵌在 config JSONB 中，无关系表

config JSONB 结构 (按 strategy_type 不同):
  selection:
    {
      "groups": [
        {"group_id": "...", "name": "...",
         "rules": [{"rule_id": "...", "weight": 1.0, "params": {...}}, ...],
         "fusion": {"method": "and|or|...", "weights": {...},
                    "long_threshold": 0.5, "short_threshold": -0.5}},
        ...
      ],
      "group_fusion": {"method": "and|or|...", ...},
      "top_n": 50
    }
  timing:
    {
      "groups": [
        {"group_id": "...", "name": "...",
         "rules": [{"rule_id": "...", "weight": 1.0, "params": {...}}, ...],
         "fusion": {"method": "and|or|...", "weights": {...},
                    "buy_threshold": 0.5, "sell_threshold": 0.5}},
        ...
      ],
      "group_fusion": {"method": "and|or|...", ...},
      "position_config": {"plugin_class": "...", "params": {...}, "factor_ids": [...]}
    }
"""

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase

from ..enums import StrategyStatus, StrategyType


class Strategy(AuditedBase):
    """策略定义 — 截面选股 OR 时序回测的完整配置"""

    __bind_key__ = "trading"
    __tablename__ = "td_strategy"

    strategy_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, comment="策略编码（业务唯一标识）",
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="策略名称")
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, default="", comment="策略说明",
    )
    strategy_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=StrategyType.SELECTION,
        comment="策略类型: selection(截面选股) / timing(时序回测)",
    )
    config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
        comment="策略主配置（groups + group_fusion + 类型特有配置）",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=StrategyStatus.DRAFT,
        comment="状态: draft/active/deprecated",
    )

    __table_args__ = ({"comment": "策略定义"},)
