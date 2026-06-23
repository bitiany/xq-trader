"""回测 API 请求/响应模型"""

from datetime import date

from pydantic import BaseModel, Field


class BacktestRunRequest(BaseModel):
    """回测运行请求 — 运行时参数从此处注入

    设计原则:
      - strategy_id 指定"如何做"（策略配置）
      - symbols/日期/资金 指定"对什么、什么时候、用多少钱做"（运行时参数）
      - 不接受 selection_run_id，标的列表必须由调用方直接传入
    """

    strategy_id: str = Field(..., description="策略编码 → td_strategy.strategy_id")
    symbols: list[str] = Field(..., min_length=1, description="回测标的列表（运行时入参）")
    start_date: date = Field(..., description="回测起始日期")
    end_date: date = Field(..., description="回测结束日期")
    initial_cash: float = Field(default=1000000, gt=0, description="初始资金")
    commission: float = Field(default=0.0003, ge=0, description="手续费率")


class BacktestRunResponse(BaseModel):
    """回测运行响应"""

    run_id: str
    strategy_id: str
    status: str
    metrics_per_symbol: dict = Field(..., description="每个标的的绩效指标")
