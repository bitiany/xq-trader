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
from typing import Any

import pandas as pd

from framework.dal.transaction.transactional import transactional
from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry
from xqtrader.domain.factor.models.factor_value import FacFactorValue
from xqtrader.domain.factor.services.factor_data_loader import (
    load_financial_composite_panel,
    load_financial_pit_panel,
)
from xqtrader.domain.factor.services.on_demand_compute_registry import get_registry
from xqtrader.domain.market.models.candlestick import CandlestickDaily

from ..backtest.core import StrategyConfig
from ..backtest.runner import run_backtest
from ..enums import BacktestRunStatus
from ..loaders import StrategyConfigLoader
from ..models.backtest import BacktestResult, BacktestRun
from .on_demand_registration import register_default_on_demand_computes

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

        从 CandlestickDaily 加载行情，从因子表加载因子值：
          - 日频因子（含日频合成因子）: FacFactorValue（按 trade_date 精确匹配）
          - 季频单因子: FacFinancialFactorValue（PIT + 向前填充到日频）
          - 季频合成因子: FacFinancialCompositeValue（PIT + 向前填充到日频）

        合并为一个 DataFrame，列名小写。

        on_demand 因子（macd/ma/boll/缠论/九转等因子库无 precomputed 版本的战术指标）
        由 OnDemandComputeRegistry 实时计算（§19.3），需要预热数据，因此加载时向前
        扩展 120 个交易日，计算指标后再截取到目标日期范围。
        """
        factor_ids = strategy_config.get_all_factor_ids()

        # 确保注册表已初始化（API lifespan 或 worker 首次执行时幂等注册）
        register_default_on_demand_computes()
        registry = get_registry()

        # 区分 on_demand 因子（注册表实时计算）和 DB 因子（从因子库加载）
        # 因子库已有的 precomputed 因子（rsi_14/bias_6/mom_5d/kdj_k/adx_14/boll_width 等）
        # 不在 on_demand 注册表中，自动走 DB 加载路径（§5.4：禁止重复实现 precomputed 因子）
        on_demand_factor_ids = {fid for fid in factor_ids if registry.is_on_demand_factor(fid)}

        # on_demand 因子需要预热（talib 指标需要历史数据），向前扩展 120 个交易日
        warmup_days = 120 if on_demand_factor_ids else 0
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

        # 因子分流加载：on_demand 因子（注册表实时计算）/ DB 因子（从因子库加载）
        # on_demand 因子由 OnDemandComputeRegistry 统一计算（§5.4：禁止重复实现 precomputed 因子）
        # 此处仅加载 DB 因子，避免 merge 时列名冲突产生 _x/_y 后缀
        db_factor_ids = [fid for fid in factor_ids if fid not in on_demand_factor_ids]
        if db_factor_ids:
            # 查询因子注册表，按 update_freq 分流
            regs = await FacFactorRegistry.filter(factor_id__in=db_factor_ids)
            reg_map: dict[str, FacFactorRegistry] = {r.factor_id: r for r in regs}

            # 仅日频因子走 FacFactorValue（含日频合成因子 composite_alpha 等）
            daily_factor_ids: list[str] = []
            quarterly_pit_ids: list[str] = []      # 季频单因子（fina_indicator）
            quarterly_composite_ids: list[str] = []  # 季频合成因子（update_freq=quarterly）

            for fid in db_factor_ids:
                reg = reg_map.get(fid)
                if reg is None:
                    daily_factor_ids.append(fid)
                    continue
                update_freq = reg.update_freq or "daily"
                origin = reg.data_origin or "computed"
                if update_freq == "quarterly" and origin == "computed":
                    quarterly_composite_ids.append(fid)
                elif origin == "fina_indicator":
                    quarterly_pit_ids.append(fid)
                else:
                    daily_factor_ids.append(fid)

            # 1) 日频因子：批量从 FacFactorValue 加载
            if daily_factor_ids:
                factor_records = await FacFactorValue.filter(
                    symbol=symbol,
                    pool_id="all",
                    trade_date__gte=warmup_start,
                    trade_date__lte=end_date,
                    factor_id__in=daily_factor_ids,
                )
                if factor_records:
                    factor_df = pd.DataFrame([
                        {"trade_date": pd.Timestamp(r.trade_date), r.factor_id: float(r.factor_value)}
                        for r in factor_records
                        if r.factor_value is not None
                    ])
                    factor_df = factor_df.groupby("trade_date").agg("first").reset_index()
                    df = df.merge(factor_df, on="trade_date", how="left")
                    # 周频合成因子（update_freq=weekly，如 composite_alpha）向前填充到日频：
                    # 周频更新日之间保持上一次值，使信号在非更新日也能正常触发
                    weekly_factor_ids = [
                        fid for fid in daily_factor_ids
                        if reg_map.get(fid) and (reg_map[fid].update_freq or "daily") == "weekly"
                    ]
                    if weekly_factor_ids:
                        df[weekly_factor_ids] = df[weekly_factor_ids].ffill()

            # 2) 季频单因子：PIT + 向前填充到日频
            for fid in quarterly_pit_ids:
                pit_panel = await load_financial_pit_panel(
                    warmup_start, end_date, fid, [symbol],
                )
                if pit_panel.empty:
                    continue
                sym_series = pit_panel.xs(symbol, level="symbol")[fid]
                sym_series.index = pd.to_datetime(sym_series.index)
                df = df.merge(
                    sym_series.rename(fid).reset_index(),
                    on="trade_date",
                    how="left",
                )

            # 3) 季频合成因子：PIT + 向前填充到日频
            for fid in quarterly_composite_ids:
                comp_panel = await load_financial_composite_panel(
                    warmup_start, end_date, fid, [symbol], pool_id="all",
                )
                if comp_panel.empty:
                    continue
                sym_series = comp_panel.xs(symbol, level="symbol")[fid]
                sym_series.index = pd.to_datetime(sym_series.index)
                df = df.merge(
                    sym_series.rename(fid).reset_index(),
                    on="trade_date",
                    how="left",
                )

        # 缺失因子列填充 NaN — backtrader PandasData 支持 NaN，_read_factor_values
        # 会将 NaN 转为 None，ExpressionPlugin 检测到 None 后返回 neutral（"因子数据缺失"）。
        # 不使用 fillna(0.0) — 0.0 是合法因子值，可能错误触发 >= 0 / <= 0 类信号。
        for fid in factor_ids:
            if fid not in df.columns:
                df[fid] = float("nan")

        # on_demand 因子统一经 OnDemandComputeRegistry 计算
        # （§5.4：禁止对 fac_factor_registry 中已存在的 precomputed 因子在业务层重复实现；
        #  §19.3：BacktestService 统一经 OnDemandComputeRegistry 加载战术指标）
        if on_demand_factor_ids:
            requested = sorted(on_demand_factor_ids)
            computed = registry.compute_factors(df, requested)
            for col in computed.columns:
                df[col] = computed[col].values

        # 截取到目标日期范围（丢弃预热期数据）
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        df = df[(df["trade_date"] >= start_ts) & (df["trade_date"] <= end_ts)].reset_index(drop=True)

        # 因子数据覆盖率诊断 — 覆盖率过低的因子会导致信号稀疏
        BacktestService._log_factor_coverage(df, factor_ids, on_demand_factor_ids, symbol)

        return df

    @staticmethod
    def _log_factor_coverage(
        df: pd.DataFrame,
        factor_ids: list[str],
        on_demand_factor_ids: set[str],
        symbol: str,
    ) -> None:
        """诊断因子数据覆盖率 — 覆盖率过低的因子会导致信号稀疏。

        on_demand 因子（MACD/RSI/缠论 等）由 OnDemandComputeRegistry 实时计算，
        覆盖率取决于 K 线数据，不需要诊断。仅诊断 DB 加载的 precomputed 因子。
        """
        total_rows = len(df)
        if total_rows == 0:
            return
        db_factor_ids = [fid for fid in factor_ids if fid not in on_demand_factor_ids]
        low_coverage: list[str] = []
        for fid in db_factor_ids:
            if fid not in df.columns:
                continue
            valid_count = int(df[fid].notna().sum())
            coverage = valid_count / total_rows
            if coverage < 0.5:
                low_coverage.append(f"{fid}={coverage:.1%}({valid_count}/{total_rows})")
        if low_coverage:
            logger.warning(
                "标的 %s 因子数据覆盖率过低，可能导致信号稀疏: %s",
                symbol, ", ".join(low_coverage),
            )
