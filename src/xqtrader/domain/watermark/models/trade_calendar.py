from datetime import date

from sqlalchemy import Boolean, Date, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base

DEFAULT_TRADE_EXCHANGE = "SSE"


class TradeCalendar(Base):
    """交易日历表 - 存储各交易所的开休市日期"""

    __bind_key__ = "default"
    __tablename__ = "t_trade_calendar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True, comment="主键ID")
    exchange: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="交易所代码：SSE/SZSE/BSE"
    )
    cal_date: Mapped[date] = mapped_column(Date, nullable=False, index=True, comment="日历日期")
    is_open: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否交易日：true/false"
    )
    pretrade_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="上一交易日日期")

    __table_args__ = (
        UniqueConstraint("exchange", "cal_date", name="uq_trade_calendar_exchange_cal_date"),
        {"comment": "交易日历表 - 存储各交易所的开休市日期"},
    )

    @classmethod
    async def get_latest_trade_date(
        cls,
        *,
        exchange: str = DEFAULT_TRADE_EXCHANGE,
        on_or_before: date | None = None,
    ) -> date | None:
        """返回 on_or_before 当日及之前最近的一个交易日。"""
        ref = on_or_before or date.today()
        rows = await cls.filter(
            exchange=exchange,
            is_open=True,
            cal_date__lte=ref,
            order_by=cls.cal_date.desc(),
            limit=1,
        )
        if not rows:
            return None
        return rows[0].cal_date

    @classmethod
    async def count_trading_days_after(
        cls,
        after: date,
        through: date,
        *,
        exchange: str = DEFAULT_TRADE_EXCHANGE,
    ) -> int:
        """统计 (after, through] 区间内的交易日数量，用于计算滞后交易日。"""
        if after >= through:
            return 0
        return await cls.count(
            exchange=exchange,
            is_open=True,
            cal_date__gt=after,
            cal_date__lte=through,
        )
