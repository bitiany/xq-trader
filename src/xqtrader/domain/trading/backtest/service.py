"""回测服务 — 加载策略 + 加载数据 + 执行回测 + 落库

依赖:
  - StrategyConfigLoader: DB → StrategyConfig
  - backtest.runner.run_backtest: 单标的回测
  - 数据加载: CandlestickDaily + 因子数据（DailyIndicator 等）
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any, cast

import numpy as np
import pandas as pd
import talib as ta

from framework.dal.transaction.transactional import transactional
from xqtrader.domain.factor.models.factor_value import FacFactorValue
from xqtrader.domain.market.models.candlestick import CandlestickDaily

from ..backtest.core import StrategyConfig
from ..backtest.runner import run_backtest
from ..enums import BacktestRunStatus
from ..loaders import StrategyConfigLoader
from ..models.backtest import BacktestResult, BacktestRun

logger = logging.getLogger(__name__)


class BacktestService:
    """回测运行服务 — 协调策略加载、数据加载、回测执行、结果持久化"""

    async def execute(
        self,
        strategy_id: str,
        symbols: list[str],
        start_date: date,
        end_date: date,
        initial_cash: float,
        commission: float = 0.0003,
    ) -> dict[str, Any]:
        """执行回测，返回绩效摘要

        Args:
            strategy_id: 策略编码
            symbols: 回测标的列表（运行时入参，与策略配置解耦）
            start_date: 开始日期
            end_date: 结束日期
            initial_cash: 初始资金
            commission: 手续费率

        Returns:
            {run_id, metrics_per_symbol, aggregated}
        """
        # 1. 创建运行记录
        run_id = str(uuid.uuid4())
        run = await self._create_run(
            run_id, strategy_id, symbols, start_date, end_date, initial_cash, commission,
        )

        try:
            # 2. 加载策略配置
            strategy_config = await StrategyConfigLoader.load(strategy_id)

            # 3. 标记运行中
            await run.update({"status": BacktestRunStatus.RUNNING, "started_at": datetime.now()})

            # 4. 逐标的执行回测
            results_per_symbol: dict[str, dict[str, Any]] = {}
            for symbol in symbols:
                df = await self._load_data(symbol, strategy_config, start_date, end_date)
                if df is None or df.empty:
                    logger.warning(f"标的 {symbol} 数据为空，跳过")
                    continue

                perf = run_backtest(
                    df=df,
                    strategy_config=strategy_config,
                    symbol=symbol,
                    start_date=start_date.strftime("%Y-%m-%d"),
                    end_date=end_date.strftime("%Y-%m-%d"),
                    cash=initial_cash,
                    commission=commission,
                )
                results_per_symbol[symbol] = perf

            # 5. 落库
            await self._persist_result(run_id, results_per_symbol)
            await run.update({
                "status": BacktestRunStatus.SUCCESS,
                "finished_at": datetime.now(),
            })

            return {
                "run_id": run_id,
                "strategy_id": strategy_id,
                "status": BacktestRunStatus.SUCCESS,
                "metrics_per_symbol": results_per_symbol,
            }

        except Exception as e:
            logger.error(f"回测执行失败: run_id={run_id}", exc_info=True)
            await run.update({
                "status": BacktestRunStatus.FAILED,
                "finished_at": datetime.now(),
                "error_message": str(e)[:500],
            })
            raise

    @staticmethod
    @transactional(bind_key="trading")
    async def _create_run(
        run_id: str,
        strategy_id: str,
        symbols: list[str],
        start_date: date,
        end_date: date,
        initial_cash: float,
        commission: float,
    ) -> BacktestRun:
        return await BacktestRun.create(
            run_id=run_id,
            strategy_id=strategy_id,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
            commission=commission,
            status=BacktestRunStatus.PENDING,
        )

    @staticmethod
    @transactional(bind_key="trading")
    async def _persist_result(run_id: str, metrics_per_symbol: dict[str, dict]) -> None:
        existing = await BacktestResult.get_or_none(run_id=run_id)
        if existing is not None:
            await existing.update({"metrics": metrics_per_symbol})
            return
        await BacktestResult.create(
            run_id=run_id,
            metrics=metrics_per_symbol,
            equity_curve=[],
            trades=[],
        )

    @staticmethod
    async def _load_data(
        symbol: str,
        strategy_config: StrategyConfig,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame | None:
        """加载标的 OHLCV + 因子数据

        从 CandlestickDaily 加载行情，从 DailyIndicator/FactorValue 加载因子。
        合并为一个 DataFrame，列名小写。

        内置技术因子（MACD/RSI 等）需要预热数据，因此加载时向前扩展 120 个交易日，
        计算指标后再截取到目标日期范围。
        """
        factor_ids = strategy_config.get_all_factor_ids()
        builtin_factor_ids = BacktestService._get_builtin_factor_ids(factor_ids)

        # 需要预热时，向前扩展 120 个交易日（约 6 个月）
        warmup_days = 120 if builtin_factor_ids else 0
        warmup_start = start_date - timedelta(days=warmup_days * 2)  # 日历日约为交易日 2 倍

        # OHLCV — 含预热期
        candles = await CandlestickDaily.filter(
            symbol=symbol,
            trade_date__gte=warmup_start,
            trade_date__lte=end_date,
            order_by=CandlestickDaily.trade_date,
        )
        if not candles:
            return None

        df = pd.DataFrame([
            {
                "trade_date": pd.Timestamp(c.trade_date),
                "open": float(c.open),
                "high": float(c.high),
                "low": float(c.low),
                "close": float(c.close),
                "volume": int(c.volume),
            }
            for c in candles
        ])

        # 加载因子（仅 fac_factor_value 内的因子，DailyIndicator/FinancialIndicator 按需扩展）
        # 内置技术因子由 _add_builtin_technical_factors 计算，
        # 此处仅加载非内置因子，避免 merge 时列名冲突产生 _x/_y 后缀
        db_factor_ids = [fid for fid in factor_ids if fid not in builtin_factor_ids]
        if db_factor_ids:
            factor_records = await FacFactorValue.filter(
                symbol=symbol,
                pool_id="all",
                trade_date__gte=warmup_start,
                trade_date__lte=end_date,
                factor_id__in=db_factor_ids,
            )
            if factor_records:
                factor_df = pd.DataFrame([
                    {"trade_date": pd.Timestamp(r.trade_date), r.factor_id: float(r.factor_value)}
                    for r in factor_records
                    if r.factor_value is not None
                ])
                factor_df = factor_df.groupby("trade_date").agg("first").reset_index()
                df = df.merge(factor_df, on="trade_date", how="left")

        # 缺失因子列填 0（避免 backtrader 数据源报错）
        for fid in factor_ids:
            if fid not in df.columns:
                df[fid] = 0.0
            else:
                df[fid] = df[fid].fillna(0.0)

        # 内置技术因子在 DB 因子之后计算，确保覆盖缺失或为 0 的值
        BacktestService._add_builtin_technical_factors(df, factor_ids)

        # 截取到目标日期范围（丢弃预热期数据）
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        df = df[(df["trade_date"] >= start_ts) & (df["trade_date"] <= end_ts)].reset_index(drop=True)

        return df

    @staticmethod
    def _get_builtin_factor_ids(factor_ids: list[str]) -> set[str]:
        """返回由 _add_builtin_technical_factors 计算的因子 ID 集合。"""
        builtin = set()
        macd_related = {"macd", "signal", "hist", "hist_slope", "hist_area"}
        if set(factor_ids).intersection(macd_related):
            builtin.update(macd_related)
        if "rsi" in factor_ids:
            builtin.add("rsi")
        if "bias" in factor_ids:
            builtin.add("bias")
        if "mon_5d" in factor_ids:
            builtin.add("mon_5d")
        return builtin

    @staticmethod
    def _add_builtin_technical_factors(df: pd.DataFrame, factor_ids: list[str]) -> None:
        """按需计算轻量回测内置技术因子。"""
        required = set(factor_ids)
        close = df["close"].astype(float)
        close_values = cast(
            np.ndarray[tuple[Any, ...], np.dtype[np.float64]],
            close.to_numpy(dtype=np.float64),
        )

        if required.intersection({"macd", "signal", "hist", "hist_slope", "hist_area"}):
            macd, signal, hist = ta.MACD(close_values, fastperiod=12, slowperiod=26, signalperiod=9)
            df["macd"] = macd
            df["signal"] = signal
            df["hist"] = hist * 2  # 国内主流机构实现：hist = 2 * (MACD - Signal)
            df["hist_slope"] = df["hist"] - df["hist"].shift(5)
            df["hist_area"] = df["hist"].rolling(5).apply(
                BacktestService._calc_hist_area,
                raw=False,
            )

        if "rsi" in required:
            df["rsi"] = ta.RSI(close_values, timeperiod=14)

        if "bias" in required:
            ma6 = close.rolling(6).mean()
            df["bias"] = (close - ma6) / ma6 * 100

        if "mon_5d" in required:
            df["mon_5d"] = close / close.shift(5) - 1

    @staticmethod
    def _calc_hist_area(window: pd.Series) -> float:
        pos = window[window > 0].sum()
        neg = window[window < 0].sum()
        return float(pos if window.iloc[-1] > 0 else neg)
