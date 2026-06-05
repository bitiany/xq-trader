from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base


class Security(Base):
    __bind_key__ = "stock"
    __tablename__ = "sdc_security"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True, comment="证券代码")
    code: Mapped[str] = mapped_column(String(20), comment="TS代码")
    name: Mapped[str] = mapped_column(String(100), comment="证券名称")
    area: Mapped[str] = mapped_column(String(50), comment="地域")
    industry: Mapped[str] = mapped_column(String(50), comment="所属行业")
    fullname: Mapped[str] = mapped_column(String(100), comment="证券全称")
    enname: Mapped[str] = mapped_column(String(100), comment="英文全称")
    cnspell: Mapped[str] = mapped_column(String(50), comment="拼音缩写")
    market: Mapped[str] = mapped_column(String(50), comment="市场类型")
    exchange: Mapped[str] = mapped_column(String(50), comment="交易所")
    board_type: Mapped[str] = mapped_column(String(20), comment="板块类型")
    curr_type: Mapped[str] = mapped_column(String(20), comment="交易货币类型")
    list_date: Mapped[str] = mapped_column(String(20), comment="上市日期")
    list_status: Mapped[str] = mapped_column(String(10), comment="上市状态")
    del_date: Mapped[str | None] = mapped_column(String(20), default=None, comment="退市日期")
    is_hs: Mapped[str] = mapped_column(String(10), comment="是否沪深港通标的")
    act_name: Mapped[str | None] = mapped_column(String(100), default=None, comment="实控人名称")
    act_type: Mapped[str | None] = mapped_column(String(10), default=None, comment="实控人类型")
    introduction: Mapped[str | None] = mapped_column(Text, default=None, comment="公司简介")

    __table_args__ = ({"comment": "证券基本信息表"},)
