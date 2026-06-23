"""选股 API 请求/响应模型。"""

from datetime import date

from pydantic import BaseModel, Field


class SelectionRunRequest(BaseModel):
    """选股运行请求。"""

    strategy_id: str = Field(..., description="策略编码 → td_strategy.strategy_id")
    signal_date: date = Field(..., description="信号日期")
    universe_type: str = Field(
        default="full_market",
        description="样本池类型: full_market(全市场) / index(指数成分) / custom(自定义)",
    )
    universe_param: str | None = Field(
        default=None,
        description="样本池参数: index 类型时为 pool_id (idx_50/idx_300/idx_500/idx_1000)",
    )
    custom_symbols: list[str] | None = Field(
        default=None,
        description="自定义标的列表: universe_type=custom 时使用",
    )
    top_n: int = Field(default=50, ge=1, le=500, description="返回前 N 名")


class SelectionRunResponse(BaseModel):
    """选股运行响应。"""

    strategy_id: str
    signal_date: date
    universe_type: str
    universe_size: int = Field(..., description="样本池标的数量")
    selected_count: int = Field(..., description="入选标的数量")
    elapsed_ms: int = Field(..., description="耗时毫秒")
    items: list[dict] = Field(..., description="选股结果列表，按得分倒序")
    factor_labels: dict[str, str] = Field(default_factory=dict, description="因子显示名称映射")
    filter_steps: list[dict] = Field(default_factory=list, description="规则筛选统计步骤")
