"""交易域 Pydantic Schemas"""

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


# ---- 账户 ----
class AccountCreate(BaseModel):
    account_code: str = Field(..., max_length=32, description="账户编码")
    account_name: str = Field(..., max_length=64, description="账户名称")
    account_type: str = Field(default="live", description="live/paper")
    broker_type: str = Field(default="qmt", description="qmt/simulated/backtest")
    broker_config: dict[str, Any] = Field(default_factory=dict, description="券商连接配置")
    initial_capital: Decimal = Field(default=Decimal("0"), description="初始资金")
    description: str = ""


class AccountUpdate(BaseModel):
    account_name: str | None = None
    broker_config: dict[str, Any] | None = None
    initial_capital: Decimal | None = None
    is_enabled: bool | None = None
    description: str | None = None


# ---- 策略实例 ----
class InstanceCreate(BaseModel):
    account_id: int = Field(..., description="交易账户ID")
    strategy_id: int | None = Field(default=None, description="策略定义ID")
    instance_name: str = Field(..., max_length=128, description="实例名称")
    run_mode: str = Field(default="live_manual", description="live_manual/live_auto/paper/backtest")
    config: dict[str, Any] = Field(default_factory=dict, description="策略运行时配置")
    position_sizing: dict[str, Any] = Field(default_factory=dict, description="仓位管理配置")
    risk_overrides: dict[str, Any] = Field(default_factory=dict, description="风控规则覆盖")
    universe_pool: str = ""
    description: str = ""


class InstanceUpdate(BaseModel):
    instance_name: str | None = None
    config: dict[str, Any] | None = None
    position_sizing: dict[str, Any] | None = None
    risk_overrides: dict[str, Any] | None = None
    universe_pool: str | None = None
    description: str | None = None


# ---- 自选池 ----
class WatchlistItemCreate(BaseModel):
    symbol: str = Field(..., max_length=16, description="证券代码")
    sizing_config: dict[str, Any] = Field(default_factory=dict)
    signal_config: dict[str, Any] = Field(default_factory=dict)
    target_weight: Decimal | None = None
    note: str = ""


class WatchlistItemUpdate(BaseModel):
    symbol: str | None = Field(default=None, max_length=16, description="证券代码")
    sizing_config: dict[str, Any] | None = None
    signal_config: dict[str, Any] | None = None
    target_weight: Decimal | None = None
    is_enabled: int | None = None
    note: str | None = None


# ---- 风控规则 ----
class RiskRuleUpdate(BaseModel):
    is_enabled: bool | None = Field(default=None, description="启用/禁用")


class RiskEventResolveRequest(BaseModel):
    resolved_by: str = Field(default="user", max_length=64, description="处理人")


class ManualDecisionWorkflowRequest(BaseModel):
    signal_date: str | None = Field(default=None, description="信号日 YYYY-MM-DD；不传则使用最新因子交易日")
    execution_date: str | None = Field(default=None, description="执行日 YYYY-MM-DD；不传则为信号日后一日")
    lookback_days: int = Field(default=120, ge=1, le=500, description="信号计算回看天数")
    min_confidence: float = Field(default=0.6, ge=0, le=1, description="组合信号最小置信度")
    max_selected: int = Field(default=10, ge=1, le=100, description="最多入选信号数")


# ---- 预订单 ----
class PreOrderUpdate(BaseModel):
    target_weight: float | None = Field(default=None, description="目标权重")
    target_qty: int | None = Field(default=None, description="目标数量")
    order_type: str | None = Field(default=None, description="limit/market")
    limit_price: Decimal | None = Field(default=None, description="限价")


class ApprovalRequest(BaseModel):
    approved: bool = Field(..., description="true=批准, false=拒绝")
    approved_by: str = Field(default="system", max_length=64, description="审批人")
    comment: str = Field(default="", max_length=256, description="审批意见")


class BatchApprovalRequest(BaseModel):
    pre_order_ids: list[int] = Field(..., description="预订单ID列表")
    approved: bool = Field(..., description="true=批准, false=拒绝")
    approved_by: str = Field(default="system", max_length=64, description="审批人")
    comment: str = Field(default="", max_length=256, description="审批意见")
