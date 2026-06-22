"""因子预计算器 — 回测前加载因子数据 + OHLCV + 计算技术指标。

输出 {symbol: DataFrame}，每只标的的 DataFrame 包含:
  - OHLCV: open, high, low, close, volume, amount
  - 因子列: 各 factor_id 的值（来自 fac_factor_value）
  - 指标列: 各技术指标的值（talib 计算）

该 DataFrame 将被 FactorDataFeed (Phase 5) 注入 backtrader 作为 DataFeed lines，
供 XqTraderStrategy 在 next() 内构建 RuleContext 调用 SignalEngine。

设计原则:
  - 一次性加载所有数据，避免回测中 I/O
  - 因子与技术指标分列存储，backtrader 内逐 bar 读取
  - 指标计算需要历史数据，预加载额外天数
  - 回测与截面选股职责分离 — 本模块只加载时序因子，不做截面选股
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd

from framework.commons.logger import get_logger

from .indicators import IndicatorSpec, TechnicalIndicatorCalculator

logger = get_logger(__name__)

# 预加载额外天数（指标计算需要历史数据，如 MA20 需要 20 个交易日）
_PRELOAD_EXTRA_DAYS = 90

# 查询分片大小，避免单次 IN 列表过长
_QUERY_BATCH_SIZE = 500


@dataclass
class PrecomputeConfig:
    """因子预计算配置。

    Attributes:
        symbols: 标的列表
        start_date: 回测起始日期
        end_date: 回测结束日期
        factor_ids: 需加载的因子 ID 列表（来自时序规则依赖）
        indicator_specs: 需计算的技术指标规格列表
        pool_id: 因子样本池标识，默认 all
    """

    symbols: list[str]
    start_date: date
    end_date: date
    factor_ids: list[str] = field(default_factory=list)
    indicator_specs: list[IndicatorSpec] = field(default_factory=list)
    pool_id: str = "all"

    @property
    def preload_start_date(self) -> date:
        """指标计算所需的预加载起始日期。"""
        return self.start_date - timedelta(days=_PRELOAD_EXTRA_DAYS)


class FactorPrecomputer:
    """因子预计算器 — 加载因子 + OHLCV + 计算指标，输出 per-symbol DataFrame。

    用法:
        config = PrecomputeConfig(
            symbols=["000001.SZ", "600000.SH"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
            factor_ids=["momentum_20d", "volatility_20d"],
            indicator_specs=parse_indicator_specs([{"name": "atr", "params": {"period": 14}}]),
        )
        precomputer = FactorPrecomputer()
        data = await precomputer.precompute(config)
        # data = {"000001.SZ": DataFrame, "600000.SH": DataFrame}
    """

    async def precompute(self, config: PrecomputeConfig) -> dict[str, pd.DataFrame]:
        """执行预计算，返回 {symbol: DataFrame}。

        每个 DataFrame 按 trade_date 索引，列包含 OHLCV + 因子 + 技术指标。
        预加载区间（preload_start_date ~ start_date）的数据保留，
        供 backtrader 指标初始化使用。
        """
        if not config.symbols:
            return {}

        ohlcv_map = await self._load_ohlcv(
            config.symbols,
            config.preload_start_date,
            config.end_date,
        )
        if not ohlcv_map:
            logger.warning("OHLCV 数据为空，无法预计算")
            return {}

        factor_map: dict[str, pd.DataFrame] = {}
        if config.factor_ids:
            factor_map = await self._load_factors(
                config.symbols,
                config.preload_start_date,
                config.end_date,
                config.factor_ids,
                config.pool_id,
            )

        result: dict[str, pd.DataFrame] = {}
        for symbol, ohlcv in ohlcv_map.items():
            df = ohlcv.copy()
            if symbol in factor_map:
                df = df.join(factor_map[symbol], how="left")
            if config.indicator_specs:
                indicator_df = TechnicalIndicatorCalculator.compute_all(
                    config.indicator_specs, df,
                )
                # 检测因子列与指标列名冲突
                conflict_cols = set(df.columns) & set(indicator_df.columns) - {"trade_date"}
                if conflict_cols:
                    logger.warning(
                        f"因子/指标列名冲突 symbol={symbol} columns={conflict_cols}，"
                        "指标列将覆盖因子列",
                    )
                df = pd.concat([df, indicator_df], axis=1)
                # 去除冲突产生的重复列（保留后出现的指标列）
                df = df.loc[:, ~df.columns.duplicated()]
            result[symbol] = df

        logger.info(
            f"因子预计算完成: symbols={len(result)}/{len(config.symbols)} | "
            f"factors={len(config.factor_ids)} | indicators={len(config.indicator_specs)}",
        )
        return result

    # ==================== 数据加载 ====================

    async def _load_ohlcv(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
    ) -> dict[str, pd.DataFrame]:
        """批量加载多标的 OHLCV 数据。

        Returns:
            {symbol: DataFrame[trade_date, open, high, low, close, volume, amount]}
        """
        from xqtrader.domain.market.models.candlestick import CandlestickDaily

        symbol_rows: dict[str, list[dict[str, Any]]] = {}
        for i in range(0, len(symbols), _QUERY_BATCH_SIZE):
            batch = symbols[i:i + _QUERY_BATCH_SIZE]
            records = await CandlestickDaily.filter(
                symbol__in=batch,
                trade_date__gte=start_date,
                trade_date__lte=end_date,
            )
            for r in records:
                symbol_rows.setdefault(r.symbol, []).append({
                    "trade_date": r.trade_date,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                    "amount": r.amount,
                })

        result: dict[str, pd.DataFrame] = {}
        for symbol, rows in symbol_rows.items():
            df = pd.DataFrame(rows).set_index("trade_date").sort_index()
            result[symbol] = df

        logger.debug(f"OHLCV 加载完成: {len(result)}/{len(symbols)} 只标的有数据")
        return result

    async def _load_factors(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        factor_ids: list[str],
        pool_id: str,
    ) -> dict[str, pd.DataFrame]:
        """批量加载多标的因子数据。

        Returns:
            {symbol: DataFrame[trade_date, factor_id1, factor_id2, ...]}
        """
        from xqtrader.domain.factor.models.factor_value import FacFactorValue

        all_rows: list[dict[str, Any]] = []
        for i in range(0, len(symbols), _QUERY_BATCH_SIZE):
            batch = symbols[i:i + _QUERY_BATCH_SIZE]
            records = await FacFactorValue.filter(
                symbol__in=batch,
                trade_date__gte=start_date,
                trade_date__lte=end_date,
                factor_id__in=factor_ids,
                pool_id=pool_id,
            )
            all_rows.extend(
                {
                    "trade_date": r.trade_date,
                    "symbol": r.symbol,
                    r.factor_id: r.factor_value,
                }
                for r in records
                if r.factor_value is not None
            )

        if not all_rows:
            logger.warning(f"因子数据为空: factor_ids={factor_ids} | symbols={symbols[:5]} | pool_id={pool_id}")
            return {}

        df = pd.DataFrame(all_rows)
        df = df.groupby(["trade_date", "symbol"]).agg("first").reset_index()

        result: dict[str, pd.DataFrame] = {}
        for symbol, group in df.groupby("symbol"):
            symbol_str = str(symbol)
            symbol_df = group.drop(columns=["symbol"]).set_index("trade_date").sort_index()
            result[symbol_str] = symbol_df

        logger.info(
            f"因子数据加载: {len(all_rows)} 条记录 | "
            f"factor_ids={factor_ids} | symbols={len(result)}/{len(symbols)}",
        )

        logger.debug(f"因子数据加载完成: {len(result)}/{len(symbols)} 只标的有因子数据")
        return result
