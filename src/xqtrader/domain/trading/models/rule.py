"""规则引擎 — 规则注册表 & 规则-因子依赖"""

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase, Base

from ..enums import RuleCategory, RuleStatus, RuleType


class RuleRegistry(AuditedBase):
    """规则注册表 — 表达式规则与 SPI 插件规则的统一注册"""

    __bind_key__ = "trading"
    __tablename__ = "td_rule_registry"

    rule_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, comment="规则唯一标识",
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="规则名称")
    category: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RuleCategory.BOTH,
        comment="类别: cross_section/time_series/both",
    )
    type: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RuleType.EXPRESSION,
        comment="类型: expression/spi",
    )
    expression: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="表达式字符串(type=expression)",
    )
    spi_class: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="SPI插件类路径(type=spi)",
    )
    factors: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default=[], comment="依赖因子列表",
    )
    signal_mapping: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default={}, comment="信号映射配置",
    )
    config_schema: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default={}, comment="参数JSON Schema",
    )
    default_config: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default={}, comment="默认配置参数",
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, default="", comment="规则说明",
    )
    is_builtin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否内置规则",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RuleStatus.ACTIVE,
        comment="状态: active/deprecated",
    )

    __table_args__ = ({"comment": "规则注册表"},)


class RuleFactorDep(Base):
    """规则-因子依赖 — 记录规则与因子注册表的关联"""

    __bind_key__ = "trading"
    __tablename__ = "td_rule_factor_dep"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, comment="PK",
    )
    rule_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, comment="规则ID",
    )
    factor_id: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
        comment="因子ID → fac_factor_registry",
    )
    usage: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default="", comment="用途说明",
    )

    __table_args__ = ({"comment": "规则-因子依赖"},)
