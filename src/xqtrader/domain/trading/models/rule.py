"""规则注册表 — 单表 JSONB 配置

规则定义集中在 RuleRegistry.definition JSONB 字段中，按 rule_type 不同:

definition JSONB 结构:
  rule_type = "expression" + category = "timing":
    {"buy_expr": "rsi_14 < 30", "sell_expr": "rsi_14 > 70", "prev_factors": []}

  rule_type = "expression" + category = "selection":
    {"bullish_expr": "pe < 20 and roe > 0.15",
     "bearish_expr": "pe > 80 or roe < 0",
     "score_expr": "rank(-pe) * 0.5 + rank(roe) * 0.5"}

  rule_type = "plugin":
    {"plugin_class": "xqtrader.domain.trading.backtest.plugins.macd.MACDPlugin",
     "default_params": {"fast": 12, "slow": 26}}
"""

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase

from ..enums import RuleCategory, RuleStatus, RuleType


class RuleRegistry(AuditedBase):
    """规则注册表 — 表达式规则与 SPI 插件规则的统一注册

    与 Strategy 解耦: Strategy.config 通过 rule_id 引用本表，
    避免规则配置在多个策略中重复定义。
    """

    __bind_key__ = "trading"
    __tablename__ = "td_rule_registry"

    rule_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, comment="规则编码（业务唯一标识）",
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="规则名称")
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, default="", comment="规则说明",
    )
    category: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RuleCategory.BOTH,
        comment="类别: selection(仅截面) / timing(仅时序) / both(均可)",
    )
    rule_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RuleType.EXPRESSION,
        comment="类型: expression(表达式) / plugin(SPI 插件)",
    )
    definition: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict,
        comment="规则定义（按 rule_type 不同：buy/sell/bullish/bearish 表达式或 plugin_class）",
    )
    factors: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, default=list, comment="依赖因子列表 ['pe', 'roe']",
    )
    is_builtin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否内置规则",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RuleStatus.ACTIVE,
        comment="状态: active/deprecated",
    )

    __table_args__ = ({"comment": "规则注册表"},)
