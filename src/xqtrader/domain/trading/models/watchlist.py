"""自选池 & 自选股条目"""

from sqlalchemy import Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase


class Watchlist(AuditedBase):
    """自选池 — 每个账户一个自选池"""

    __bind_key__ = "trading"
    __tablename__ = "td_watchlist"

    account_id: Mapped[int] = mapped_column(
        Integer, nullable=False, unique=True, comment="账户ID(1:1)",
    )
    name: Mapped[str] = mapped_column(
        String(64), nullable=False, default="默认自选池", comment="池名称",
    )
    description: Mapped[str | None] = mapped_column(
        String(256), nullable=True, default="", comment="说明",
    )

    __table_args__ = ({"comment": "自选池"},)


class WatchlistItem(AuditedBase):
    """自选股条目 — 池内标的，可覆盖实例级配仓/信号配置"""

    __bind_key__ = "trading"
    __tablename__ = "td_watchlist_item"

    watchlist_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True, comment="自选池ID",
    )
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, comment="证券代码")
    sizing_config: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default={}, comment="个股配仓配置(覆盖实例默认)",
    )
    signal_config: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, default={}, comment="个股信号配置(覆盖实例默认)",
    )
    target_weight: Mapped[float | None] = mapped_column(
        Numeric(8, 6), nullable=True, default=None, comment="目标权重",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="排序",
    )
    is_enabled: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, comment="是否启用 0/1",
    )
    note: Mapped[str | None] = mapped_column(
        String(256), nullable=True, default="", comment="备注",
    )

    __table_args__ = ({"comment": "自选股条目"},)
