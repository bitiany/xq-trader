"""XqTraderStrategy — backtrader 策略，调用 SignalEngine + PositionSizingEngine。

每个 bar 内执行:
  1. 逐标的构建 RuleContext（从 DataFeed lines 读取因子/指标值）
  2. 调用 SignalEngine.evaluate_symbol() 生成时序信号
  3. 调用 SignalFusionEngine.fuse() 融合截面×时序信号
  4. 构建 PortfolioState（从 broker adapter 读取持仓）
  5. 调用 PositionSizingEngine.compute_weights() 计算目标仓位
  6. 通过 BacktestBrokerAdapter 提交订单

设计原则:
  - 回测与截面选股职责分离 — 策略只做信号→交易→成交
  - SignalEngine / PositionSizingEngine 环境无关，此处调用同步核心
  - 因子值从 DataFeed lines 读取，因子时序从预计算 DataFrame 切片
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import backtrader as bt
import pandas as pd

from framework.commons.logger import get_logger

from ..rules.base import RuleContext, SelectionScore
from ..signals import SignalEngine, SignalFusionEngine, SignalResult
from ..sizing import PortfolioState, PositionInfo, SizingResult
from .broker_adapter import BacktestBrokerAdapter

logger = get_logger(__name__)

# 权重变动阈值，低于此值不调仓（避免频繁微调）
_REBALANCE_THRESHOLD = 0.005


class XqTraderStrategy(bt.Strategy):
    """回测策略 — 因子驱动的多标的信号生成 + 仓位管理 + 订单执行。

    Params:
        signal_engine: SignalEngine 实例（已 prepare）
        sizing_engine: PositionSizingEngine 实例（已 prepare）
        factor_data: {symbol: DataFrame} 预计算数据
        factor_ids: 规则依赖的因子 ID 列表
        indicator_columns: 技术指标列名列表
        selection_results: 截面选股结果（可选，None=纯时序模式）
        lookback_days: 因子时序回看天数
    """

    params = (
        ("signal_engine", None),
        ("sizing_engine", None),
        ("factor_data", None),
        ("factor_ids", None),
        ("indicator_columns", None),
        ("selection_results", None),
        ("lookback_days", 60),
    )

    def __init__(self) -> None:
        self._broker_adapter = BacktestBrokerAdapter(self)
        # backtrader params 在运行时动态展开为属性，mypy 无法识别
        self._signal_engine: SignalEngine = self.params.signal_engine  # type: ignore[attr-defined]
        self._sizing_engine = self.params.sizing_engine  # type: ignore[attr-defined]
        self._factor_data: dict[str, pd.DataFrame] = self.params.factor_data or {}  # type: ignore[attr-defined]
        self._factor_ids: list[str] = list(self.params.factor_ids or [])  # type: ignore[attr-defined]
        self._indicator_columns: list[str] = list(self.params.indicator_columns or [])  # type: ignore[attr-defined]
        self._selection: dict[str, SelectionScore] | None = self.params.selection_results  # type: ignore[attr-defined]

        indicator_only = [c for c in self._indicator_columns if c not in self._factor_ids]
        self._all_columns: list[str] = self._factor_ids + indicator_only

        for data in self.datas:
            symbol = getattr(data, "_name", "")
            if symbol:
                self._broker_adapter.register_data(symbol, data)

        logger.info(
            f"XqTraderStrategy 初始化 | datas={len(self.datas)} | "
            f"factors={len(self._factor_ids)} | indicators={len(indicator_only)} | "
            f"selection={'fusion' if self._selection else 'time_series_only'}",
        )

    def next(self) -> None:
        """逐 bar 执行：信号生成 → 融合 → 仓位计算 → 下单。"""
        current_date = self.data.datetime.date(0)

        signals = self._evaluate_signals(current_date)
        if not signals:
            return

        fused = SignalFusionEngine.fuse(self._selection, signals)

        portfolio = self._build_portfolio_state(current_date)
        results = self._sizing_engine.compute_weights(fused, portfolio)
        self._submit_orders(results)

    # ==================== 信号生成 ====================

    def _evaluate_signals(self, current_date: date) -> dict[str, SignalResult]:
        """逐标的评估时序信号。"""
        signals: dict[str, SignalResult] = {}
        for data in self.datas:
            symbol = getattr(data, "_name", "")
            if not symbol:
                continue
            context = self._build_context(symbol, data, current_date)
            try:
                signals[symbol] = self._signal_engine.evaluate_symbol(context)
            except Exception as e:
                logger.error(
                    f"信号评估失败: symbol={symbol} date={current_date} error={e}",
                    exc_info=True,
                )
                # 异常时跳过该标的，不参与后续融合和仓位计算
        return signals

    def _build_context(
        self,
        symbol: str,
        data: Any,
        current_date: date,
    ) -> RuleContext:
        """从 DataFeed lines + 预计算 DataFrame 构建 RuleContext。"""
        factor_values: dict[str, float] = {}
        for col in self._all_columns:
            line = getattr(data.lines, col, None)
            if line is not None:
                val = line[0]
                # 排除 NaN 和 inf（backtrader 缺失列返回 0.0，需一并排除）
                if math.isfinite(val):
                    factor_values[col] = float(val)

        factor_series: dict[str, pd.Series] = {}
        if symbol in self._factor_data:
            df = self._factor_data[symbol]
            # precomputer 输出的 index 可能是 date 或 DatetimeIndex
            # 统一转为 date 后用 date 切片，避免类型不匹配
            if isinstance(df.index, pd.DatetimeIndex):
                slice_end: date | pd.Timestamp = pd.Timestamp(current_date)
            else:
                slice_end = current_date
            lookback_df = df.loc[:slice_end].tail(self.params.lookback_days)  # type: ignore[attr-defined]
            for col in self._all_columns:
                if col in lookback_df.columns:
                    series = lookback_df[col].dropna()
                    if not series.empty:
                        factor_series[col] = series

        return RuleContext(
            symbol=symbol,
            signal_date=current_date,
            factor_values=factor_values,
            factor_series=factor_series,
        )

    # ==================== 仓位管理 ====================

    def _build_portfolio_state(self, current_date: date) -> PortfolioState:
        """从 broker adapter 构建 PortfolioState。"""
        account = self._broker_adapter.get_account()
        positions = self._broker_adapter.get_positions()

        pos_dict: dict[str, PositionInfo] = {}
        for symbol, pos in positions.items():
            weight = pos.market_value / account.total_value if account.total_value > 0 else 0.0
            pos_dict[symbol] = PositionInfo(
                symbol=symbol,
                qty=round(pos.qty),
                avg_price=pos.avg_price,
                market_value=pos.market_value,
                weight=weight,
            )

        return PortfolioState(
            current_date=current_date,
            cash=account.cash,
            total_value=account.total_value,
            positions=pos_dict,
        )

    def _submit_orders(self, results: dict[str, SizingResult]) -> None:
        """根据目标权重提交订单。"""
        for symbol, result in results.items():
            current_weight = result.current_weight or 0.0
            if abs(result.target_weight - current_weight) > _REBALANCE_THRESHOLD:
                self._broker_adapter.order_target_percent(symbol, result.target_weight)

    def stop(self) -> None:
        """回测结束，记录最终状态。"""
        account = self._broker_adapter.get_account()
        logger.info(
            f"回测结束 | final_value={account.total_value:.2f} | "
            f"cash={account.cash:.2f} | positions={len(self._broker_adapter.get_positions())}",
        )
