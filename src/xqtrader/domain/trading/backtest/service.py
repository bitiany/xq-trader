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
from xqtrader.domain.factor.models.factor_registry import FacFactorRegistry
from xqtrader.domain.factor.models.factor_value import FacFactorValue
from xqtrader.domain.factor.services.factor_data_loader import (
    load_financial_composite_panel,
    load_financial_pit_panel,
)
from xqtrader.domain.market.models.candlestick import CandlestickDaily

from ..backtest.core import StrategyConfig
from ..backtest.plugins.chanlun_signal import compute_chanlun_signals
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

        从 CandlestickDaily 加载行情，从因子表加载因子值：
          - 日频因子（含日频合成因子）: FacFactorValue（按 trade_date 精确匹配）
          - 季频单因子: FacFinancialFactorValue（PIT + 向前填充到日频）
          - 季频合成因子: FacFinancialCompositeValue（PIT + 向前填充到日频）

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

        # 因子分流加载：内置因子 / 日频因子 / 季频因子 / 季频合成因子
        # 内置技术因子由 _add_builtin_technical_factors 计算，
        # 此处仅加载非内置因子，避免 merge 时列名冲突产生 _x/_y 后缀
        db_factor_ids = [fid for fid in factor_ids if fid not in builtin_factor_ids]
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

        # 内置技术因子在 DB 因子之后计算，确保覆盖缺失或为 0 的值
        BacktestService._add_builtin_technical_factors(df, factor_ids)

        # 截取到目标日期范围（丢弃预热期数据）
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date)
        df = df[(df["trade_date"] >= start_ts) & (df["trade_date"] <= end_ts)].reset_index(drop=True)

        # 因子数据覆盖率诊断 — 覆盖率过低的因子会导致信号稀疏
        BacktestService._log_factor_coverage(df, factor_ids, builtin_factor_ids, symbol)

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
        # 缠论信号 — 基于 OHLCV 实时计算，不依赖 DB 因子库
        chan_related = {"chan_buy_point", "chan_sell_point", "chan_bi_direction"}
        if set(factor_ids).intersection(chan_related):
            builtin.update(chan_related)
        # KDJ 指标
        kdj_related = {"kdj_k", "kdj_d", "kdj_j"}
        if set(factor_ids).intersection(kdj_related):
            builtin.update(kdj_related)
        # 布林带
        boll_related = {"boll_upper", "boll_middle", "boll_lower", "boll_width"}
        if set(factor_ids).intersection(boll_related):
            builtin.update(boll_related)
        # 均线
        ma_related = {"ma_short", "ma_long"}
        if set(factor_ids).intersection(ma_related):
            builtin.update(ma_related)
        # 量价因子
        vol_related = {"vol_ma_20", "vol_ratio"}
        if set(factor_ids).intersection(vol_related):
            builtin.update(vol_related)
        # ADX 趋势强度（含 +DI / -DI 用于方向判断）
        adx_related = {"adx", "adx_plus_di", "adx_minus_di"}
        if set(factor_ids).intersection(adx_related):
            builtin.update(adx_related)
        # ATR 波动率
        if "atr" in factor_ids:
            builtin.add("atr")
        # 动量因子（已有 mon_5d，新增 mon_10d/mon_20d）
        mon_related = {"mon_5d", "mon_10d", "mon_20d"}
        if set(factor_ids).intersection(mon_related):
            builtin.update(mon_related)
        # 神奇九转 TD Sequential
        td_related = {"td_seq_buy", "td_seq_sell", "td_seq_count"}
        if set(factor_ids).intersection(td_related):
            builtin.update(td_related)
        # close 也作为内置因子（从 OHLCV 直接获取）
        if "close" in factor_ids:
            builtin.add("close")
        return builtin

    @staticmethod
    def _add_builtin_technical_factors(df: pd.DataFrame, factor_ids: list[str]) -> None:
        """按需计算轻量回测内置技术因子。

        因子库数据 + 按需实时计算结合：
          - MACD/RSI/BIAS/KDJ/布林带/均线等技术指标由 talib/pandas 实时计算
          - 缠论信号由 chanpy 实时计算笔/中枢/背驰
          - 资金流/动量等因子从 DB 加载
        """
        required = set(factor_ids)
        close = df["close"].astype(float)
        close_values = cast(
            np.ndarray[tuple[Any, ...], np.dtype[np.float64]],
            close.to_numpy(dtype=np.float64),
        )
        high_values = cast(
            np.ndarray[tuple[Any, ...], np.dtype[np.float64]],
            df["high"].astype(float).to_numpy(dtype=np.float64),
        )
        low_values = cast(
            np.ndarray[tuple[Any, ...], np.dtype[np.float64]],
            df["low"].astype(float).to_numpy(dtype=np.float64),
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

        # 10日/20日动量
        if "mon_10d" in required:
            df["mon_10d"] = close / close.shift(10) - 1
        if "mon_20d" in required:
            df["mon_20d"] = close / close.shift(20) - 1

        # KDJ 指标 — 国内主流实现：RSV -> K -> D -> J
        kdj_related = {"kdj_k", "kdj_d", "kdj_j"}
        if required.intersection(kdj_related):
            kdj_k, kdj_d = BacktestService._calc_kdj(high_values, low_values, close_values)
            df["kdj_k"] = kdj_k
            df["kdj_d"] = kdj_d
            df["kdj_j"] = 3 * kdj_k - 2 * kdj_d

        # 布林带 — middle=SMA20, upper/lower=middle±2*std
        boll_related = {"boll_upper", "boll_middle", "boll_lower", "boll_width"}
        if required.intersection(boll_related):
            boll_middle = close.rolling(20).mean()
            boll_std = close.rolling(20).std()
            df["boll_middle"] = boll_middle
            df["boll_upper"] = boll_middle + 2 * boll_std
            df["boll_lower"] = boll_middle - 2 * boll_std
            # 布林带宽度（归一化）
            df["boll_width"] = (df["boll_upper"] - df["boll_lower"]) / boll_middle

        # 均线 — ma_short=MA5, ma_long=MA20
        ma_related = {"ma_short", "ma_long"}
        if required.intersection(ma_related):
            df["ma_short"] = close.rolling(5).mean()
            df["ma_long"] = close.rolling(20).mean()

        # 成交量均线 — 用于量价突破判断
        if "vol_ma_20" in required:
            df["vol_ma_20"] = df["volume"].astype(float).rolling(20).mean()

        # 量比 — 当日成交量 / 5日平均成交量（衡量成交活跃度）
        if "vol_ratio" in required:
            vol_ma5 = df["volume"].astype(float).rolling(5).mean()
            df["vol_ratio"] = df["volume"].astype(float) / vol_ma5.replace(0, np.nan)

        # ADX 趋势强度（DI+/DI-/ADX） — 衡量趋势强度，不区分方向
        adx_related = {"adx", "adx_plus_di", "adx_minus_di"}
        if required.intersection(adx_related):
            adx_vals = ta.ADX(high_values, low_values, close_values, timeperiod=14)
            plus_di = ta.PLUS_DI(high_values, low_values, close_values, timeperiod=14)
            minus_di = ta.MINUS_DI(high_values, low_values, close_values, timeperiod=14)
            df["adx"] = adx_vals
            df["adx_plus_di"] = plus_di
            df["adx_minus_di"] = minus_di

        # ATR 波动率 — 用于止损止盈与突破强度判断
        if "atr" in required:
            df["atr"] = ta.ATR(high_values, low_values, close_values, timeperiod=14)

        # 神奇九转 TD Sequential — 经典反转信号
        # Setup: 连续9个 close < close.shift(4) → 买入信号
        #        连续9个 close > close.shift(4) → 卖出信号
        td_related = {"td_seq_buy", "td_seq_sell", "td_seq_count"}
        if required.intersection(td_related):
            BacktestService._calc_td_sequential(df)

        # 缠论买卖点信号 — 基于 OHLCV 实时计算笔/中枢/背驰
        # 缠论不作为截面因子入库，回测时直接由 chanpy 实时计算
        chan_factor_ids = {"chan_buy_point", "chan_sell_point", "chan_bi_direction"}
        if required.intersection(chan_factor_ids):
            chan_signals = compute_chanlun_signals(df)
            for col in chan_signals.columns:
                df[col] = chan_signals[col].values

    @staticmethod
    def _calc_td_sequential(df: pd.DataFrame) -> None:
        """计算神奇九转 TD Sequential 指标

        TD Setup 经典规则:
          买入信号: 连续 9 个交易日收盘价 < 4 日前收盘价（下跌动能衰竭）
          卖出信号: 连续 9 个交易日收盘价 > 4 日前收盘价（上涨动能衰竭）

        计数中断条件:
          - 连续计数中断后归零，重新开始
          - 第 9 根 K 线确认后产生信号

        输出列:
          td_seq_buy: 1.0=买入信号触发, 0.0=否
          td_seq_sell: 1.0=卖出信号触发, 0.0=否
          td_seq_count: 正数=上涨计数(卖出预警), 负数=下跌计数(买入预警)
        """
        n = len(df)
        close = df["close"].astype(float)
        buy_signal = np.zeros(n)
        sell_signal = np.zeros(n)
        td_count = np.zeros(n)

        if n < 9:
            df["td_seq_buy"] = buy_signal
            df["td_seq_sell"] = sell_signal
            df["td_seq_count"] = td_count
            return

        # close.shift(4) — 4 日前收盘价
        close_prev4 = close.shift(4)

        up_count = 0   # 连续 close > close.shift(4) 的天数（卖出预警）
        down_count = 0  # 连续 close < close.shift(4) 的天数（买入预警）

        for i in range(4, n):
            curr = close.iloc[i]
            prev4 = close_prev4.iloc[i]
            if pd.isna(curr) or pd.isna(prev4):
                td_count[i] = up_count if up_count > 0 else -down_count
                continue

            if curr > prev4:
                up_count += 1
                down_count = 0
            elif curr < prev4:
                down_count += 1
                up_count = 0
            else:
                # 相等不计数，重置
                up_count = 0
                down_count = 0

            # 第 9 根确认信号
            if up_count == 9:
                sell_signal[i] = 1.0
                # 信号触发后重置计数（避免重复触发）
                up_count = 0
            if down_count == 9:
                buy_signal[i] = 1.0
                down_count = 0

            td_count[i] = up_count if up_count > 0 else -down_count

        df["td_seq_buy"] = buy_signal
        df["td_seq_sell"] = sell_signal
        df["td_seq_count"] = td_count

    @staticmethod
    def _calc_kdj(
        high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 9,
    ) -> tuple[np.ndarray, np.ndarray]:
        """计算 KDJ 指标的 K 和 D 值

        国内主流实现:
          RSV = (close - lowest_low_n) / (highest_high_n - lowest_low_n) * 100
          K = 前K * 2/3 + RSV * 1/3
          D = 前D * 2/3 + K * 1/3

        Args:
            high: 最高价数组
            low: 最低价数组
            close: 收盘价数组
            period: RSV 计算周期（默认9日）

        Returns:
            (K, D) 数组
        """
        n = len(close)
        k = np.full(n, np.nan)
        d = np.full(n, np.nan)
        if n < period:
            return k, d

        # 滚动计算最高价和最低价
        for i in range(period - 1, n):
            highest = np.max(high[i - period + 1:i + 1])
            lowest = np.min(low[i - period + 1:i + 1])
            if highest == lowest:
                rsv = 50.0
            else:
                rsv = (close[i] - lowest) / (highest - lowest) * 100

            if i == period - 1:
                k[i] = 50 * 2 / 3 + rsv * 1 / 3
                d[i] = 50 * 2 / 3 + k[i] * 1 / 3
            else:
                k[i] = k[i - 1] * 2 / 3 + rsv * 1 / 3
                d[i] = d[i - 1] * 2 / 3 + k[i] * 1 / 3

        return k, d

    @staticmethod
    def _calc_hist_area(window: pd.Series) -> float:
        pos = window[window > 0].sum()
        neg = window[window < 0].sum()
        return float(pos if window.iloc[-1] > 0 else neg)

    @staticmethod
    def _log_factor_coverage(
        df: pd.DataFrame,
        factor_ids: list[str],
        builtin_factor_ids: set[str],
        symbol: str,
    ) -> None:
        """诊断因子数据覆盖率 — 覆盖率过低的因子会导致信号稀疏。

        内置技术因子（MACD/RSI 等）由 _add_builtin_technical_factors 计算，
        覆盖率取决于 K 线数据，不需要诊断。仅诊断 DB 加载的因子。
        """
        total_rows = len(df)
        if total_rows == 0:
            return
        db_factor_ids = [fid for fid in factor_ids if fid not in builtin_factor_ids]
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
