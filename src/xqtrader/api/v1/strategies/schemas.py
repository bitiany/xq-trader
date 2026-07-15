"""策略管理 Pydantic Schemas — 简化为单 config JSONB"""

from datetime import date
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


class StrategySignalRequest(BaseModel):
    """策略信号判定请求 — 批量执行 SPI 插件 evaluate()。"""

    symbol: str = Field(..., description="标的代码，如 600519.SH")
    strategies: list[str] = Field(
        ...,
        description="策略名称列表，如 ['chanlun', 'macd_cross']",
    )
    as_of: date = Field(..., description="信号日期（交易日）")


# ── 策略择时历史 Schemas（§20 阶段 5） ──────────────────────────────


class TimingHistoryRecordRequest(BaseModel):
    """记录一次 strategy-timing 信号请求。"""

    symbol: str = Field(..., description="标的代码，如 600519.SH")
    as_of: date = Field(..., description="择时日期（交易日）")
    aggregated_signal: str = Field(..., description="综合聚合信号: buy/hold/sell")
    confidence: float = Field(..., ge=0.0, le=1.0, description="综合置信度 0.0-1.0")
    signals: list[dict[str, Any]] = Field(
        ...,
        description="各策略信号列表 [{strategy_name, strategy_category, rule_id, "
        "signal, score, confidence, reason, detail, factor_ids_consumed}]",
    )
    market_regime: str | None = Field(
        default=None,
        description="市场状态推断: trending_up/down/sideways/volatile",
    )
    decision_rationale: str | None = Field(default=None, description="AI 综合聚合决策理由")


class CompareOutcomeRequest(BaseModel):
    """走势比对请求。"""

    window_days: int = Field(default=5, ge=1, le=30, description="走势比对窗口天数")

