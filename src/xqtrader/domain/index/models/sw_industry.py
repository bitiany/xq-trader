"""申万行业分类 ORM 模型。"""

from sqlalchemy import Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base


class SwIndustry(Base):
    """申万行业分类表"""

    __bind_key__ = "stock"
    __tablename__ = "sdc_sw_industry"

    industry_code: Mapped[str] = mapped_column(String(32), primary_key=True, comment="行业代码")
    index_code: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="行业指数代码")
    industry_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="行业名称")
    level: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="行业级别 1/2/3")
    parent_code: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="父级行业代码")
    is_pub: Mapped[str | None] = mapped_column(String(4), nullable=True, comment="是否发布")
    change_reason: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="变更原因")
    version: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="版本号")
    daily_status: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="日线状态")

    __table_args__ = ({"comment": "申万行业分类表"},)


class SwIndustryMember(Base):
    """申万行业成分股表"""

    __bind_key__ = "stock"
    __tablename__ = "sdc_sw_industry_member"

    industry_code: Mapped[str] = mapped_column(String(32), primary_key=True, comment="行业代码")
    con_code: Mapped[str] = mapped_column(String(32), primary_key=True, comment="成分股代码")
    con_name: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="成分股名称")
    in_date: Mapped[Date | None] = mapped_column(Date, nullable=True, comment="纳入日期")
    out_date: Mapped[Date | None] = mapped_column(Date, nullable=True, comment="调出日期")
    is_new: Mapped[str | None] = mapped_column(String(4), nullable=True, comment="是否最新")

    __table_args__ = ({"comment": "申万行业成分股表"},)
