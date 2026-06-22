"""BacktestEngine — 回测编排器，串联预计算 → 数据注入 → 策略运行 → 绩效收集。

编排流程:
  1. 异步初始化: SignalEngine.prepare() + PositionSizingEngine.prepare() + FactorPrecomputer.precompute()
  2. 同步运行: 创建 DataFeed → 配置 Cerebro → 添加策略 → 运行回测
  3. 收集结果: 从 analyzer 提取绩效指标，构建 BacktestResult

设计原则:
  - 回测与截面选股职责分离 — 引擎只编排信号→交易→成交
  - 因子与技术指标在回测前一次性预计算，回测中无 I/O
  - SignalEngine / PositionSizingEngine 环境无关，引擎调用同步核心
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import backtrader as bt
import pandas as pd

from framework.commons.logger import get_logger

from ..models.strategy import Strategy
from ..rules.base import SelectionScore
from ..signals import SignalEngine
from ..sizing import PositionSizingEngine, SizingContext
from .constants import TRADING_DAYS_PER_YEAR
from .data_feed import collect_extra_columns, create_data_feed
from .indicators import IndicatorSpec
from .precomputer import FactorPrecomputer, PrecomputeConfig
from .strategy import XqTraderStrategy

logger = get_logger(__name__)


@dataclass
class BacktestConfig:
    """回测配置。

    Attributes:
        strategy_id: 策略 ID
        symbols: 标的列表
        start_date: 回测起始日期
        end_date: 回测结束日期
        initial_capital: 初始资金
        commission_rate: 佣金费率（单边）
        slippage: 滑点（百分比）
        indicator_specs: 技术指标规格列表
        selection_results: 截面选股结果（可选，None=纯时序模式）
        lookback_days: 因子时序回看天数
    """

    strategy_id: str
    symbols: list[str]
    start_date: date
    end_date: date
    initial_capital: float = 1_000_000.0
    commission_rate: float = 0.0003
    slippage: float = 0.001
    indicator_specs: list[IndicatorSpec] = field(default_factory=list)
    selection_results: dict[str, SelectionScore] | None = None
    lookback_days: int = 60


@dataclass
class BacktestResult:
    """回测结果。

    Attributes:
        strategy_id: 策略 ID
        start_date: 回测起始日期
        end_date: 回测结束日期
        initial_capital: 初始资金
        final_value: 最终资产
        total_return: 总收益率
        annual_return: 年化收益率
        max_drawdown: 最大回撤
        sharpe_ratio: 夏普比率
        total_trades: 总交易笔数
        daily_returns: 日收益率序列（供 QuantStats 使用）
        equity_curve: 权益曲线
    """

    strategy_id: str
    start_date: date
    end_date: date
    initial_capital: float
    final_value: float
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    total_trades: int
    daily_returns: pd.Series
    equity_curve: pd.Series


class BacktestEngine:
    """回测引擎 — 编排预计算 → 数据注入 → 策略运行 → 绩效收集。

    用法:
        config = BacktestConfig(
            strategy_id="momentum_001",
            symbols=["000001.SZ", "600000.SH"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
            indicator_specs=parse_indicator_specs([{"name": "atr", "params": {"period": 14}}]),
        )
        engine = BacktestEngine(config)
        result = await engine.run()
    """

    def __init__(self, config: BacktestConfig) -> None:
        self._config = config
        self._cerebro = bt.Cerebro(stdstats=False, preload=True, runonce=False)
        self._signal_engine: SignalEngine | None = None
        self._sizing_engine: PositionSizingEngine | None = None
        self._factor_data: dict[str, pd.DataFrame] = {}
        self._factor_ids: list[str] = []
        self._indicator_columns: list[str] = []

    async def run(self) -> BacktestResult:
        """执行回测，返回回测结果（初始化 + 运行一体化）。

        异步初始化（数据加载）后，同步运行回测（CPU 密集）。
        """
        logger.info(
            f"回测启动 | strategy={self._config.strategy_id} | "
            f"symbols={len(self._config.symbols)} | "
            f"period={self._config.start_date} ~ {self._config.end_date} | "
            f"capital={self._config.initial_capital}",
        )

        await self.initialize()
        return self.run_cerebro()

    async def initialize(self) -> None:
        """异步初始化 — 加载策略配置、预计算数据。

        可单独调用，与 run_cerebro() 分离以支持线程池调度。
        """
        await self._initialize()

    def run_cerebro(self) -> BacktestResult:
        """同步运行 Cerebro 回测 — CPU 密集型，可在线程池中执行。

        调用前须先调用 initialize() 完成异步初始化。
        """
        return self._run_cerebro()

    # ==================== 异步初始化 ====================

    async def _initialize(self) -> None:
        """异步初始化 — 加载策略配置、预计算数据。"""
        self._signal_engine = SignalEngine(self._config.strategy_id)
        await self._signal_engine.prepare()

        # 检测时序规则组 — 无时序规则且无截面选股结果时无法生成交易信号
        has_ts_rules = self._signal_engine.has_time_series_rules()
        has_selection = self._config.selection_results is not None
        if not has_ts_rules and not has_selection:
            msg = (
                f"策略 {self._config.strategy_id} 无时序规则组且无截面选股结果，"
                "无法生成交易信号。请在策略中配置时序规则组或传入截面选股结果。"
            )
            raise ValueError(msg)

        strategy = await Strategy.get_or_none(strategy_id=self._config.strategy_id)
        if strategy is None:
            msg = f"策略不存在: {self._config.strategy_id}"
            raise ValueError(msg)
        self._sizing_engine = PositionSizingEngine(strategy)
        await self._sizing_engine.prepare(SizingContext(
            symbols=self._config.symbols,
            start_date=self._config.start_date,
            end_date=self._config.end_date,
            initial_capital=self._config.initial_capital,
        ))

        self._factor_ids = self._signal_engine.get_required_factors()
        self._indicator_columns = self._collect_indicator_columns()

        precomputer = FactorPrecomputer()
        self._factor_data = await precomputer.precompute(PrecomputeConfig(
            symbols=self._config.symbols,
            start_date=self._config.start_date,
            end_date=self._config.end_date,
            factor_ids=self._factor_ids,
            indicator_specs=self._config.indicator_specs,
        ))

        if not self._factor_data:
            msg = "预计算数据为空，无法回测"
            raise ValueError(msg)

        logger.info(
            f"初始化完成 | factors={len(self._factor_ids)} | "
            f"indicators={len(self._indicator_columns)} | "
            f"symbols_with_data={len(self._factor_data)} | "
            f"has_ts_rules={has_ts_rules} | has_selection={has_selection}",
        )

    def _collect_indicator_columns(self) -> list[str]:
        """从指标规格列表收集所有输出列名。"""
        columns: list[str] = []
        for spec in self._config.indicator_specs:
            columns.extend(spec.output_columns)
        return columns

    # ==================== 同步运行 ====================

    def _run_cerebro(self) -> BacktestResult:
        """配置并运行 backtrader Cerebro。"""
        self._add_data_feeds()
        self._add_strategy()
        self._configure_broker()
        self._add_analyzers()

        results = self._cerebro.run()
        return self._collect_results(results)

    def _add_data_feeds(self) -> None:
        """创建 DataFeed 并添加到 Cerebro。"""
        extra_columns = collect_extra_columns(self._factor_data)
        for symbol, df in self._factor_data.items():
            data = create_data_feed(df, extra_columns, symbol)
            self._cerebro.adddata(data, name=symbol)

        logger.info(f"DataFeed 添加完成: {len(self._factor_data)} 只标的 | extra_lines={len(extra_columns)}")

    def _add_strategy(self) -> None:
        """添加 XqTraderStrategy 到 Cerebro。"""
        self._cerebro.addstrategy(
            XqTraderStrategy,
            signal_engine=self._signal_engine,
            sizing_engine=self._sizing_engine,
            factor_data=self._factor_data,
            factor_ids=self._factor_ids,
            indicator_columns=self._indicator_columns,
            selection_results=self._config.selection_results,
            lookback_days=self._config.lookback_days,
        )

    def _configure_broker(self) -> None:
        """配置 broker — 资金、佣金、滑点。"""
        self._cerebro.broker.setcash(self._config.initial_capital)
        self._cerebro.broker.setcommission(commission=self._config.commission_rate)
        if self._config.slippage > 0:
            self._cerebro.broker.set_slippage_perc(perc=self._config.slippage)

    def _add_analyzers(self) -> None:
        """添加绩效分析器。"""
        self._cerebro.addanalyzer(
            bt.analyzers.TimeReturn, timeframe=bt.TimeFrame.Days, _name="timereturn",
        )
        self._cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", timeframe=bt.TimeFrame.Days)
        self._cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
        self._cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    # ==================== 结果收集 ====================

    def _collect_results(self, results: list[Any]) -> BacktestResult:
        """从 analyzer 提取绩效指标，构建 BacktestResult。"""
        if not results:
            msg = "Cerebro 返回空结果列表，回测未产生有效策略实例"
            raise ValueError(msg)

        strat = results[0]
        extractor = ResultExtractor()

        daily_returns = extractor.extract_daily_returns(strat)
        sharpe_ratio = extractor.extract_sharpe(strat)
        max_drawdown = extractor.extract_max_drawdown(strat)
        total_trades = extractor.extract_total_trades(strat)

        final_value = float(self._cerebro.broker.getvalue())
        total_return = (final_value - self._config.initial_capital) / self._config.initial_capital

        annual_return = extractor.compute_annual_return(total_return, len(daily_returns))
        equity_curve = self._build_equity_curve(daily_returns)

        logger.info(
            f"回测结果 | final_value={final_value:.2f} | "
            f"total_return={total_return:.4%} | annual={annual_return:.4%} | "
            f"max_dd={max_drawdown:.4%} | sharpe={sharpe_ratio:.4f} | "
            f"trades={total_trades}",
        )

        return BacktestResult(
            strategy_id=self._config.strategy_id,
            start_date=self._config.start_date,
            end_date=self._config.end_date,
            initial_capital=self._config.initial_capital,
            final_value=final_value,
            total_return=total_return,
            annual_return=annual_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            total_trades=total_trades,
            daily_returns=daily_returns,
            equity_curve=equity_curve,
        )

    def _build_equity_curve(self, daily_returns: pd.Series) -> pd.Series:
        """从日收益率序列构建权益曲线。"""
        if daily_returns.empty:
            return pd.Series([self._config.initial_capital])
        return self._config.initial_capital * (1.0 + daily_returns).cumprod()


class ResultExtractor:
    """从 backtrader analyzer 提取绩效指标 — 纯计算工具类。"""

    @staticmethod
    def extract_daily_returns(strat: Any) -> pd.Series:
        """从 TimeReturn analyzer 提取日收益率序列。"""
        analysis = strat.analyzers.timereturn.get_analysis()
        if not analysis:
            return pd.Series(dtype=float)
        return pd.Series(analysis)

    @staticmethod
    def extract_sharpe(strat: Any) -> float:
        """从 SharpeRatio analyzer 提取夏普比率。"""
        analysis = strat.analyzers.sharpe.get_analysis()
        value = analysis.get("sharperatio", None)
        return float(value) if value is not None else 0.0

    @staticmethod
    def extract_max_drawdown(strat: Any) -> float:
        """从 DrawDown analyzer 提取最大回撤。"""
        analysis = strat.analyzers.drawdown.get_analysis()
        return float(analysis.max.drawdown) / 100.0

    @staticmethod
    def extract_total_trades(strat: Any) -> int:
        """从 TradeAnalyzer analyzer 提取总交易笔数。"""
        analysis = strat.analyzers.trades.get_analysis()
        # backtrader TradeAnalyzer 使用 AutoOrderedDict
        # 无交易时: analysis.total.total = 0, 无 closed 字段
        # 有交易时: analysis.total.closed = N
        try:
            total = analysis.total
            closed = total.closed
            return int(closed) if closed else 0
        except (KeyError, AttributeError):
            return 0

    @staticmethod
    def compute_annual_return(total_return: float, num_days: int) -> float:
        """计算年化收益率。"""
        if num_days <= 0:
            return 0.0
        if total_return <= -1.0:
            # 亏损 100% 或更多（杠杆），年化即 -1.0
            return -1.0
        # float ** float 在 mypy 中返回 float | complex，需显式转 float
        return float((1.0 + total_return) ** (TRADING_DAYS_PER_YEAR / num_days) - 1.0)
