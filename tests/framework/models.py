"""证券 ORM 模型。"""

from typing import NamedTuple

from sqlalchemy import String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from framework.dal.base import Base
class Security(Base):
    """证券基本信息表 - 存储股票/基金/指数等证券的基本信息"""

    __bind_key__ = "stock"
    __tablename__ = "sdc_security"

    symbol: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="证券代码，如000001.SZ"
    )
    code: Mapped[str] = mapped_column(String(20), nullable=False, comment="TS代码，如000001.SZ")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="证券名称，如平安银行")
    area: Mapped[str] = mapped_column(String(50), nullable=False, comment="地域，如广东")
    industry: Mapped[str] = mapped_column(String(50), nullable=False, comment="所属行业，如银行")
    fullname: Mapped[str] = mapped_column(String(100), nullable=False, comment="证券全称")
    enname: Mapped[str] = mapped_column(String(100), nullable=False, comment="英文全称")
    cnspell: Mapped[str] = mapped_column(String(50), nullable=False, comment="拼音缩写，如PAYH")
    market: Mapped[str] = mapped_column(String(50), nullable=False, comment="市场类型，如主板/创业板/科创板")
    exchange: Mapped[str] = mapped_column(String(50), nullable=False, comment="交易所，如SSE/SZSE/BSE")
    board_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="板块类型")
    curr_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="交易货币类型，如CNY")
    list_date: Mapped[str] = mapped_column(String(20), nullable=False, comment="上市日期，格式YYYYMMDD")
    list_status: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="上市状态：L(上市)、D(退市)、P(暂停上市)"
    )
    del_date: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="退市日期，格式YYYYMMDD")
    is_hs: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="是否沪深港通标的：S(沪股通)、H(深股通)、N(否)"
    )
    act_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="实控人名称")
    act_type: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="实控人类型")
    introduction: Mapped[str | None] = mapped_column(Text, nullable=True, comment="公司简介")

    __table_args__ = ({"comment": "证券基本信息表 - 存储股票/基金/指数等证券的基本信息"},)