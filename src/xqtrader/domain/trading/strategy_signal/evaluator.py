"""策略信号评估器 — 薄包装 SPI 插件 evaluate()，为指定 symbol + signal_date
批量执行策略信号判定。

数据三层策略（文档 §10.2，零重复原则）：
  1. 预计算因子 → 从 FacFactorValue 表读取（含前值）
  2. on_demand 因子 → OnDemandComputeRegistry.compute_factors 实时计算（含前值）
  3. 策略信号判定 → SPI 插件 evaluate() 返回 buy/sell/neutral

与 WatchlistDecisionWorkflowService 的关键差异：
  - 不依赖 StrategyConfig，直接通过 strategy_name → rule_id 映射查找插件
  - 补齐 on_demand 因子的前值（hist_prev / hist_area_prev 等）
  - 不涉及仓位/风控/下单，纯信号判定
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from framework.commons.exceptions import BusinessException
from framework.commons.logger import get_logger
from xqtrader.domain.factor.models.factor_value import FacFactorValue
from xqtrader.domain.factor.services.on_demand_compute_registry import (
    OnDemandComputeRegistry,
    RulePluginLike,
    get_registry,
)
from xqtrader.domain.market.models.candlestick import CandlestickDaily
from xqtrader.domain.trading.backtest.core import RuleContext, RuleResult
from xqtrader.domain.trading.backtest.on_demand_registration import (
    register_default_on_demand_computes,
)
from xqtrader.domain.trading.strategy_signal.registry import (
    StrategyMeta,
    get_strategy_meta,
    list_strategy_names,
)

logger = get_logger("STRATEGY.SIGNAL")


class StrategySignalEvaluator:
    """策略信号评估器 — 为指定 symbol + signal_date 批量执行 SPI 插件信号判定。"""

    _LOOKBACK_DAYS = 120

    async def evaluate_signals(
        self,
        symbol: str,
        strategies: list[str],
        as_of: date,
    ) -> dict[str, Any]:
        """批量执行策略信号判定。

        Args:
            symbol: 标的代码，如 "600519.SH"
            strategies: 策略名称列表，如 ["chanlun", "macd_cross"]
            as_of: 信号日期

        Returns:
            结构化信号结果，含 as_of / symbol / signals 列表
        """
        register_default_on_demand_computes()
        registry = get_registry()

        metas: list[StrategyMeta] = []
        plugin_infos: list[tuple[StrategyMeta, type[RulePluginLike]]] = []
        for name in strategies:
            meta = get_strategy_meta(name)
            if meta is None:
                raise BusinessException(
                    message=f"未知策略: {name}，可用策略: {', '.join(list_strategy_names())}"
                )
            plugin_cls = registry.get_plugin_by_rule_id(meta.rule_id)
            if plugin_cls is None:
                raise BusinessException(
                    message=f"策略 {name} 对应的 SPI 插件未注册: rule_id={meta.rule_id}"
                )
            metas.append(meta)
            plugin_infos.append((meta, plugin_cls))

        logger.info(
            "策略信号评估开始: symbol=%s, as_of=%s, strategies=%s",
            symbol, as_of, [m.strategy_name for m in metas],
        )

        factor_values = await self._load_all_factor_values(
            symbol, as_of, plugin_infos, registry,
        )

        signals: list[dict[str, Any]] = []
        for meta, plugin_cls in plugin_infos:
            signal_item = self._evaluate_single_plugin(
                plugin_cls, meta, symbol, as_of, factor_values,
            )
            signals.append(signal_item)

        logger.info(
            "策略信号评估完成: symbol=%s, as_of=%s, 共 %d 个策略",
            symbol, as_of, len(signals),
        )

        return {
            "as_of": as_of.isoformat(),
            "symbol": symbol,
            "signals": signals,
        }

    async def _load_all_factor_values(
        self,
        symbol: str,
        signal_date: date,
        plugin_infos: list[tuple[StrategyMeta, type[RulePluginLike]]],
        registry: OnDemandComputeRegistry,
    ) -> dict[str, float | None]:
        """汇总所有插件的因子需求，一次性加载（避免重复查询）。"""
        all_factor_ids: set[str] = set()
        all_prev_factor_ids: set[str] = set()
        for _, plugin_cls in plugin_infos:
            all_factor_ids.update(plugin_cls.factor_ids)
            all_prev_factor_ids.update(getattr(plugin_cls, "prev_factor_ids", []))

        db_ids = [fid for fid in all_factor_ids if not registry.is_on_demand_factor(fid)]
        db_prev_ids = [
            fid for fid in all_prev_factor_ids if not registry.is_on_demand_factor(fid)
        ]
        on_demand_ids = [
            fid for fid in all_factor_ids if registry.is_on_demand_factor(fid)
        ]
        on_demand_prev_ids = [
            fid for fid in all_prev_factor_ids if registry.is_on_demand_factor(fid)
        ]

        db_values = await self._load_db_factors(
            symbol, signal_date, db_ids, db_prev_ids,
        )
        on_demand_values = await self._compute_on_demand_factors(
            symbol, signal_date, on_demand_ids, on_demand_prev_ids,
        )
        return db_values | on_demand_values

    async def _load_db_factors(
        self,
        symbol: str,
        signal_date: date,
        factor_ids: list[str],
        prev_factor_ids: list[str],
    ) -> dict[str, float | None]:
        """从 FacFactorValue 表加载预计算因子（含前值）。

        前值键名约定: {factor_id}_prev，取 signal_date 前最近一条记录。
        """
        all_ids = sorted(set(factor_ids) | set(prev_factor_ids))
        if not all_ids:
            return {}
        start_date = signal_date - timedelta(days=self._LOOKBACK_DAYS)
        records = await FacFactorValue.filter(
            symbol=symbol,
            factor_id__in=all_ids,
            trade_date__gte=start_date,
            trade_date__lte=signal_date,
            limit=None,
            order_by=[FacFactorValue.factor_id.asc(), FacFactorValue.trade_date.desc()],
        )
        current_values: dict[str, float | None] = {}
        prev_values: dict[str, float | None] = {}
        for record in records:
            if (
                record.factor_id in factor_ids
                and record.trade_date == signal_date
                and record.factor_id not in current_values
            ):
                current_values[record.factor_id] = record.factor_value
            prev_key = f"{record.factor_id}_prev"
            if (
                record.factor_id in prev_factor_ids
                and record.trade_date < signal_date
                and prev_key not in prev_values
            ):
                prev_values[prev_key] = record.factor_value
        return current_values | prev_values

    async def _compute_on_demand_factors(
        self,
        symbol: str,
        signal_date: date,
        factor_ids: list[str],
        prev_factor_ids: list[str],
    ) -> dict[str, float | None]:
        """经 OnDemandComputeRegistry 实时计算 on_demand 因子（含前值）。

        warmup 使用 lookback_days*2 日历日（与 BacktestService 对齐）。
        前值从 computed 时序中取 signal_date 前一交易日的值。
        """
        if not factor_ids and not prev_factor_ids:
            return {}
        registry = get_registry()
        all_ids = sorted(set(factor_ids) | set(prev_factor_ids))
        if not registry.list_on_demand_factors():
            return {fid: None for fid in all_ids}

        warmup_start = signal_date - timedelta(days=self._LOOKBACK_DAYS * 2)
        bars = await CandlestickDaily.filter(
            symbol=symbol,
            trade_date__gte=warmup_start,
            trade_date__lte=signal_date,
            limit=None,
            order_by=CandlestickDaily.trade_date.asc(),
        )
        if not bars:
            return {fid: None for fid in all_ids}

        ohlcv_df = pd.DataFrame([
            {
                "trade_date": pd.Timestamp(b.trade_date),
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": int(b.volume),
            }
            for b in bars
        ]).set_index("trade_date")

        computed = registry.compute_factors(ohlcv_df, sorted(set(factor_ids) | set(prev_factor_ids)))
        signal_ts = pd.Timestamp(signal_date)

        if signal_ts not in computed.index:
            return {fid: None for fid in all_ids}

        prev_ts = self._find_prev_trading_day(pd.DatetimeIndex(computed.index), signal_ts)

        result: dict[str, float | None] = {}
        for fid in factor_ids:
            result[fid] = self._extract_value(computed, signal_ts, fid)
        for fid in prev_factor_ids:
            if prev_ts is not None:
                result[f"{fid}_prev"] = self._extract_value(computed, prev_ts, fid)
            else:
                result[f"{fid}_prev"] = None
        return result

    def _evaluate_single_plugin(
        self,
        plugin_cls: type[RulePluginLike],
        meta: StrategyMeta,
        symbol: str,
        signal_date: date,
        factor_values: dict[str, float | None],
    ) -> dict[str, Any]:
        """构造 RuleContext，调用 plugin.evaluate()，返回结构化信号。"""
        plugin = plugin_cls()
        context = RuleContext(
            symbol=symbol,
            signal_date=signal_date,
            factor_values=factor_values,
        )
        try:
            result: RuleResult = plugin.evaluate(context)
        except Exception:
            logger.error(
                "策略 %s evaluate 异常: symbol=%s, rule_id=%s",
                meta.strategy_name, symbol, meta.rule_id,
                exc_info=True,
            )
            return {
                "strategy_name": meta.strategy_name,
                "strategy_category": meta.category,
                "rule_id": meta.rule_id,
                "signal": "neutral",
                "score": 0.0,
                "confidence": 0.0,
                "reason": "策略评估异常，请联系管理员",
                "detail": {},
                "factor_ids_consumed": list(plugin_cls.factor_ids),
            }

        return {
            "strategy_name": meta.strategy_name,
            "strategy_category": meta.category,
            "rule_id": meta.rule_id,
            "signal": result.direction,
            "score": result.score,
            "confidence": result.confidence,
            "reason": result.reason,
            "detail": result.detail,
            "factor_ids_consumed": list(plugin_cls.factor_ids),
        }

    @staticmethod
    def _find_prev_trading_day(
        index: pd.DatetimeIndex,
        current_ts: pd.Timestamp,
    ) -> pd.Timestamp | None:
        """从 DatetimeIndex 中找 current_ts 之前最近的交易日。"""
        prev_mask = index < current_ts
        prev_dates = index[prev_mask]
        if len(prev_dates) == 0:
            return None
        return prev_dates[-1]

    @staticmethod
    def _extract_value(
        df: pd.DataFrame,
        ts: pd.Timestamp,
        factor_id: str,
    ) -> float | None:
        """从 DataFrame 中安全提取因子值，NaN/缺失返回 None。"""
        if factor_id not in df.columns:
            return None
        val = df.loc[ts, factor_id]
        if val is None or pd.isna(val):
            return None
        return float(val)  # type: ignore[arg-type]
