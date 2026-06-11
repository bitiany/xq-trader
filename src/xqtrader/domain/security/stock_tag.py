"""个股标签 ORM 模型。"""

from datetime import date

from sqlalchemy import Date, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base


class StockTag(Base):
    """个股标签表"""

    __bind_key__ = "stock"
    __tablename__ = "sdc_stock_tag"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, comment="证券代码")
    tag_key: Mapped[str] = mapped_column(String(32), nullable=False, comment="标签键")
    score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="标签分数")
    confidence: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="置信度")
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="生效日期")
    expire_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="失效日期")
    updated_at: Mapped[date | None] = mapped_column(Date, nullable=True, comment="更新日期")

    __table_args__ = ({"comment": "个股标签表"},)
