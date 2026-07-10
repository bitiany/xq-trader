"""盘内异动事件表 - 记录 TickAnomalyScanner 检测到的量价异动"""

from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import AuditedBase


class IntradayAnomaly(AuditedBase):
    """盘内异动事件表

    记录 TickAnomalyScanner 检测到的急涨急跌与量脉冲事件，
    用于事后归因与策略回测验证。
    """

    __bind_key__ = "stock"
    __tablename__ = "sd_intraday_anomaly"

    symbol: Mapped[str] = mapped_column(String(10), nullable=False, index=True, comment="证券代码")
    anomaly_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="异动类型: surge/volume_spike")
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, comment="检测时间"
    )
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True, comment="涨跌幅(%)，surge 类型适用")
    price: Mapped[float | None] = mapped_column(Float, nullable=True, comment="异动时价格")
    volume_ratio: Mapped[float | None] = mapped_column(Float, nullable=True, comment="量比，volume_spike 类型适用")
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="完整异动详情 JSON")

    __table_args__ = (
        {"comment": "盘内异动事件表 - 急涨急跌与量脉冲记录"},
    )
