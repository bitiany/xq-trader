"""规则注册表 API 请求模型。"""

from typing import Any

from pydantic import BaseModel, Field


class RuleCreate(BaseModel):
    """创建表达式规则。"""

    rule_id: str = Field(..., max_length=64, description="规则编码，全局唯一")
    name: str = Field(..., max_length=128, description="规则名称")
    category: str = Field(default="cross_section", description="cross_section/time_series/both")
    type: str = Field(default="expression", description="expression/spi")
    expression: str = Field(..., description="规则表达式，如 pe_ttm < 20 and roe > 15")
    factors: list[str] = Field(default_factory=list, description="表达式涉及的因子ID")
    signal_mapping: dict[str, Any] = Field(default_factory=dict, description="信号映射")
    default_config: dict[str, Any] = Field(default_factory=dict, description="默认配置")
    description: str = ""
    status: str = "active"


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128, description="规则名称")
    expression: str | None = Field(default=None, description="规则表达式")
    factors: list[str] | None = Field(default=None, description="表达式涉及的因子ID")
    signal_mapping: dict[str, Any] | None = None
    default_config: dict[str, Any] | None = None
    description: str | None = None
    status: str | None = None
