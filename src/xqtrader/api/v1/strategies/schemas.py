"""策略管理 Pydantic Schemas — 简化为单 config JSONB"""

from typing import Any

from pydantic import BaseModel, Field


class StrategyCreate(BaseModel):
    strategy_id: str = Field(..., max_length=64, description="策略编码（业务唯一标识）")
    name: str = Field(..., max_length=128)
    description: str = ""
    strategy_type: str = Field(
        default="selection",
        description="策略类型: selection(截面选股) / timing(时序回测)",
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="策略主配置（groups + group_fusion + 类型特有配置）",
    )
    status: str = Field(default="draft", description="draft/active/deprecated")


class StrategyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    strategy_type: str | None = None
    config: dict[str, Any] | None = None
    status: str | None = None
