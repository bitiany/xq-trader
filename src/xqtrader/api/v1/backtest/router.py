"""回测 API 路由 — 运行回测 + 绩效分析。"""

from __future__ import annotations

import asyncio
import time

import pandas as pd
from fastapi import APIRouter

from framework.commons.exceptions import BusinessException
from framework.commons.logger import get_logger
from xqtrader.api.v1.backtest.schemas import (
    BacktestRunRequest,
    BacktestRunResponse,
    IndicatorSpecRequest,
    SizerInfoResponse,
    StrategyInfoResponse,
)
from xqtrader.domain.trading.backtest import (
    BacktestConfig,
    BacktestEngine,
    IndicatorSpec,
    QuantStatsAnalyzer,
    parse_indicator_specs,
)
from xqtrader.domain.trading.backtest.constants import REPORT_DIR
from xqtrader.domain.trading.models.strategy import Strategy
from xqtrader.domain.trading.sizing.registry import get_default_registry

router = APIRouter(prefix="/backtest", tags=["回测"])
logger = get_logger(__name__)


def _build_indicator_specs(specs: list[IndicatorSpecRequest]) -> list[IndicatorSpec]:
    """将 API 请求的指标规格转换为 IndicatorSpec 列表。"""
    if not specs:
        return []
    configs = [
        {
            "name": s.name,
            "params": s.params,
            **({"output_columns": s.output_columns} if s.output_columns else {}),
        }
        for s in specs
    ]
    return parse_indicator_specs(configs)


def _series_to_list(series: pd.Series) -> list[dict[str, object]]:
    """将 pandas Series 转换为 [{date, value}] 列表。"""
    if not isinstance(series, pd.Series) or series.empty:
        return []
    return [
        {"date": str(idx.date()) if hasattr(idx, "date") else str(idx), "value": float(val)}
        for idx, val in series.items()
    ]


@router.post("/run", summary="运行回测", operation_id="run_backtest")
async def run_backtest(req: BacktestRunRequest) -> BacktestRunResponse:
    """运行回测 + QuantStats 绩效分析。

    流程:
      1. 构建 BacktestConfig（含指标规格）
      2. BacktestEngine.run() 执行回测（CPU 密集部分在线程池执行）
      3. QuantStatsAnalyzer.analyze() 生成绩效指标 + HTML 报告

    适合中小标的池（<100 标的，秒级返回）。大池场景请关注响应耗时。
    """
    if req.start_date >= req.end_date:
        raise BusinessException(message="start_date 必须早于 end_date")
    if not req.symbols:
        raise BusinessException(message="symbols 不能为空")

    indicator_specs = _build_indicator_specs(req.indicator_specs)

    config = BacktestConfig(
        strategy_id=req.strategy_id,
        symbols=req.symbols,
        start_date=req.start_date,
        end_date=req.end_date,
        initial_capital=req.initial_capital,
        commission_rate=req.commission_rate,
        slippage=req.slippage,
        indicator_specs=indicator_specs,
        lookback_days=req.lookback_days,
    )

    start = time.monotonic()

    # 1. 执行回测（异步初始化 + 同步 Cerebro 运行）
    engine = BacktestEngine(config)
    try:
        # 异步初始化（数据加载）在事件循环中执行
        await engine.initialize()
        # cerebro.run() 是 CPU 密集型同步调用，放入线程池避免阻塞事件循环
        result = await asyncio.to_thread(engine.run_cerebro)
    except ValueError as e:
        raise BusinessException(message=str(e)) from e

    # 2. 绩效分析
    html_path: str | None = None
    metrics_dict: dict[str, object] = {}
    if req.generate_report:
        analyzer = QuantStatsAnalyzer()
        report = analyzer.analyze(result, output_dir=REPORT_DIR, rf=req.rf)
        html_path = report.html_report_path
        metrics_dict = report.to_dict()["metrics"]
    else:
        # 不生成报告时仍返回基础指标
        metrics_dict = {
            "cumulative_return": result.total_return,
            "annual_return": result.annual_return,
            "sharpe_ratio": result.sharpe_ratio,
            "max_drawdown": result.max_drawdown,
        }

    elapsed_ms = int((time.monotonic() - start) * 1000)

    logger.info(
        f"回测API完成 | strategy={req.strategy_id} | "
        f"return={result.total_return:.4%} | sharpe={result.sharpe_ratio:.4f} | "
        f"elapsed={elapsed_ms}ms",
    )

    return BacktestRunResponse(
        strategy_id=result.strategy_id,
        start_date=result.start_date,
        end_date=result.end_date,
        initial_capital=result.initial_capital,
        final_value=result.final_value,
        total_return=result.total_return,
        annual_return=result.annual_return,
        max_drawdown=result.max_drawdown,
        sharpe_ratio=result.sharpe_ratio,
        total_trades=result.total_trades,
        metrics=metrics_dict,
        equity_curve=_series_to_list(result.equity_curve),
        daily_returns=_series_to_list(result.daily_returns),
        html_report_path=html_path,
        elapsed_ms=elapsed_ms,
    )


@router.get("/strategies/list", summary="获取策略列表", operation_id="list_backtest_strategies")
async def list_strategies() -> list[StrategyInfoResponse]:
    """获取可用于回测的策略列表。"""
    strategies = await Strategy.all()
    return [
        StrategyInfoResponse(
            strategy_id=s.strategy_id,
            name=s.name,
            description=s.description or "",
            mode="builtin",
            params_schema={},
        )
        for s in strategies
    ]


@router.get("/sizers/list", summary="获取仓位策略列表", operation_id="list_backtest_sizers")
async def list_sizers() -> list[SizerInfoResponse]:
    """获取可用的仓位管理策略列表。"""
    registry = get_default_registry()
    return [
        SizerInfoResponse(
            sizer_id=str(info["strategy_name"]),
            name=str(info["strategy_name"]),
            description=str(info["type"]),
            params_schema=info.get("config_schema") or {},
        )
        for info in registry.list_strategies()
    ]
