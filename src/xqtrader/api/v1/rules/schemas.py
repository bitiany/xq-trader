"""规则注册表 API 请求模型 — 简化为单 definition JSONB"""

from typing import Any

from pydantic import BaseModel, Field


class RuleCreate(BaseModel):
    """创建规则定义"""

    rule_id: str = Field(..., max_length=64, description="规则编码，业务唯一标识")
    name: str = Field(..., max_length=128, description="规则名称")
    description: str = ""
    category: str = Field(
        default="both",
        description="类别: selection(仅截面) / timing(仅时序) / both(均可)",
    )
    rule_type: str = Field(
        default="expression",
        description="类型: expression(表达式) / plugin(SPI 插件)",
    )
    definition: dict[str, Any] = Field(
        default_factory=dict,
        description="规则定义（按 rule_type 不同：buy/sell/bullish/bearish 表达式或 plugin_class）",
    )
    factors: list[str] = Field(default_factory=list, description="依赖因子列表")
    status: str = "active"


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    description: str | None = None
    category: str | None = None
    definition: dict[str, Any] | None = None
    factors: list[str] | None = None
    status: str | None = None
