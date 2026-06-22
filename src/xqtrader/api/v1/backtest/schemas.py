"""回测 API 请求/响应模型。"""

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class IndicatorSpecRequest(BaseModel):
    """技术指标规格请求。"""

    name: str = Field(..., description="指标名称: atr/ma/macd/rsi/bollinger/kdj")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="指标参数，如 {\"period\": 14}",
    )
    output_columns: list[str] | None = Field(
        default=None,
        description="输出列名列表，为空则自动生成",
    )


class BacktestRunRequest(BaseModel):
    """回测运行请求。"""

    strategy_id: str = Field(..., description="策略编码 → td_strategy.strategy_id")
    symbols: list[str] = Field(..., description="标的列表，如 [\"000001.SZ\", \"600000.SH\"]")
    start_date: date = Field(..., description="回测起始日期")
    end_date: date = Field(..., description="回测结束日期")
    initial_capital: float = Field(default=1_000_000.0, gt=0, description="初始资金")
    commission_rate: float = Field(default=0.0003, ge=0, description="佣金费率（单边）")
    slippage: float = Field(default=0.001, ge=0, description="滑点（百分比）")
    indicator_specs: list[IndicatorSpecRequest] = Field(
        default_factory=list,
        description="技术指标规格列表",
    )
    lookback_days: int = Field(default=60, ge=1, description="因子时序回看天数")
    generate_report: bool = Field(default=True, description="是否生成 HTML 绩效报告")
    rf: float = Field(default=0.0, ge=0.0, le=1.0, description="无风险利率（年化小数）")


class BacktestRunResponse(BaseModel):
    """回测运行响应。"""

    strategy_id: str
    start_date: date
    end_date: date
    initial_capital: float
    final_value: float
    total_return: float = Field(..., description="总收益率")
    annual_return: float = Field(..., description="年化收益率")
    max_drawdown: float = Field(..., description="最大回撤")
    sharpe_ratio: float = Field(..., description="夏普比率")
    total_trades: int = Field(..., description="总交易笔数")
    metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="QuantStats 绩效指标",
    )
    equity_curve: list[dict[str, Any]] = Field(
        default_factory=list,
        description="权益曲线 [{date, value}]",
    )
    daily_returns: list[dict[str, Any]] = Field(
        default_factory=list,
        description="日收益率序列 [{date, value}]",
    )
    html_report_path: str | None = Field(default=None, description="HTML 报告路径")
    elapsed_ms: int = Field(..., description="耗时毫秒")
