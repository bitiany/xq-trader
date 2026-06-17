"""策略管理 Pydantic Schemas。"""

from typing import Any

from pydantic import BaseModel, Field


class StrategyCreate(BaseModel):
    strategy_id: str = Field(..., max_length=64, description="策略编码（唯一）")
    name: str = Field(..., max_length=128)
    description: str = ""
    universe_pool: str | None = Field(default="all", description="默认样本池")
    status: str = Field(default="draft", description="draft/active/deprecated")
    cross_section_config: dict[str, Any] = Field(default_factory=dict)
    time_series_config: dict[str, Any] = Field(default_factory=dict)
    position_sizing_config: dict[str, Any] = Field(default_factory=dict)
    risk_overrides: dict[str, Any] = Field(default_factory=dict)


class StrategyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    universe_pool: str | None = None
    status: str | None = None
    cross_section_config: dict[str, Any] | None = None
    time_series_config: dict[str, Any] | None = None
    position_sizing_config: dict[str, Any] | None = None
    risk_overrides: dict[str, Any] | None = None


class RuleGroupCreate(BaseModel):
    group_type: str = Field(default="cross_section", description="cross_section/time_series")
    combination_method: str = Field(
        default="and",
        description="and/or/weighted_score/weighted_vote/ic_weighted",
    )
    combination_params: dict[str, Any] = Field(default_factory=dict)
    threshold: float | None = None


class RuleGroupUpdate(BaseModel):
    combination_method: str | None = None
    combination_params: dict[str, Any] | None = None
    threshold: float | None = None


class RuleBindingCreate(BaseModel):
    rule_id: str = Field(..., max_length=64)
    weight: float | None = 1.0
    config_override: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = 0


class RuleBindingUpdate(BaseModel):
    weight: float | None = None
    config_override: dict[str, Any] | None = None
    sort_order: int | None = None
