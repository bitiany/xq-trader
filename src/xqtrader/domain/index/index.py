"""指数 ORM 模型。"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base


class Index(Base):
    """指数基本信息表"""

    __bind_key__ = "stock"
    __tablename__ = "sdc_index"

    index_code: Mapped[str] = mapped_column(String(32), primary_key=True, comment="指数代码")
    name: Mapped[str] = mapped_column(String(256), nullable=False, comment="指数名称")
    index_type: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="指数类型")
    base_date: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="基期日期")
    base_value: Mapped[float | None] = mapped_column(Float, nullable=True, comment="基点")
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="创建时间")
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="更新时间")

    __table_args__ = ({"comment": "指数基本信息表"},)


class IndexWeight(Base):
    """指数成分股权重表"""

    __bind_key__ = "stock"
    __tablename__ = "sdc_index_weight"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    index_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="指数代码")
    stock_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="成分股代码")
    weight: Mapped[float | None] = mapped_column(Float, nullable=True, comment="权重")
    report_date: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="报告期")
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="创建时间")

    __table_args__ = ({"comment": "指数成分股权重表"},)
