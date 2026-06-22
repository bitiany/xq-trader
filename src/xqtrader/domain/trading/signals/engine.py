"""时序信号引擎 — 环境无关的时序信号评估。

核心设计:
  - prepare() 异步预加载规则组、规则绑定、插件实例
  - evaluate_symbol(context) 同步纯计算，可被 backtrader next() 与决策流共用
  - evaluate_symbol_async() 异步包装，自动加载因子数据后调用同步核心

三环境共用:
  - backtrader: prepare() → next() 内构建 RuleContext → evaluate_symbol()
  - 模拟盘/实盘: prepare() → evaluate_symbol_async() 自动加载因子
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd

from framework.commons.logger import get_logger

from ..models.strategy import Strategy, StrategyRuleBinding, StrategyRuleGroup
from ..rules.base import RuleContext, RuleResult
from ..rules.combination.and_or import AndCombination, OrCombination
from ..rules.combination.base import CombinationStrategy
from ..rules.combination.ic_weighted import ICWeightedCombination
from ..rules.combination.weighted_score import WeightedScoreCombination
from ..rules.combination.weighted_vote import WeightedVoteCombination
from ..rules.loader import RuleLoader
from ..rules.registry import RuleRegistry

logger = get_logger(__name__)

# 组合策略注册表（与 SelectionEngine 共用同一套组合方式）
_COMBINATION_STRATEGIES: dict[str, CombinationStrategy] = {
    "and": AndCombination(),
    "or": OrCombination(),
    "all": AndCombination(),  # "all" 等同于 "and" — 全部通过才通过
    "weighted_score": WeightedScoreCombination(),
    "weighted_vote": WeightedVoteCombination(),
    "ic_weighted": ICWeightedCombination(),
}
_DEFAULT_COMBINATION = WeightedScoreCombination()

# 默认回看天数（约 3 个月交易日）
_DEFAULT_LOOKBACK_DAYS = 60


@dataclass
class SignalResult:
    """时序信号结果 — 单标的的时序信号评估输出。"""

    symbol: str
    direction: str = "neutral"
    strength: float = 0.0
    confidence: float = 0.0
    rule_results: list[RuleResult] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


class SignalEngine:
    """时序信号引擎 — 环境无关，可被 backtrader/模拟盘/实盘调用。

    用法:
        engine = SignalEngine(strategy_id)
        await engine.prepare()
        # backtrader next() 内:
        signal = engine.evaluate_symbol(context)
        # 模拟盘/实盘:
        signal = await engine.evaluate_symbol_async(symbol, signal_date)
    """

    def __init__(self, strategy_id: str) -> None:
        self.strategy_id = strategy_id
        self._rule_registry = RuleRegistry()
        self._ts_groups: list[StrategyRuleGroup] = []
        self._group_bindings: dict[int, list[StrategyRuleBinding]] = {}
        self._strategy: Strategy | None = None
        self._factor_ids: list[str] = []

    async def prepare(self) -> None:
        """异步预加载策略配置、时序规则组、规则绑定、插件实例。"""
        strategy = await Strategy.get_or_none(strategy_id=self.strategy_id)
        if not strategy:
            msg = f"策略不存在: {self.strategy_id}"
            raise ValueError(msg)
        self._strategy = strategy

        rule_groups = await StrategyRuleGroup.filter(strategy_id=strategy.id)
        self._ts_groups = [g for g in rule_groups if g.group_type == "time_series"]

        if not self._ts_groups:
            logger.warning(f"策略无时序规则组: {self.strategy_id}")
            return

        all_bindings = await StrategyRuleBinding.filter(
            group_id__in=[g.id for g in self._ts_groups],
            order_by=StrategyRuleBinding.group_id,
        )
        for binding in all_bindings:
            self._group_bindings.setdefault(binding.group_id, []).append(binding)

        await RuleLoader.ensure_registered(self._rule_registry, all_bindings)
        self._factor_ids = await self._collect_factor_ids(all_bindings)

        logger.info(
            f"SignalEngine prepared | strategy={self.strategy_id} | "
            f"ts_groups={len(self._ts_groups)} | factors={len(self._factor_ids)}"
        )

    def get_required_factors(self) -> list[str]:
        """返回时序规则所需的因子 ID 列表。"""
        return list(self._factor_ids)

    def has_time_series_rules(self) -> bool:
        """是否有时序规则组。"""
        return len(self._ts_groups) > 0

    def evaluate_symbol(self, context: RuleContext) -> SignalResult:
        """同步核心 — 逐标的评估时序信号（纯计算，无 I/O）。

        backtrader next() 与模拟盘/实盘决策流共用此方法。
        """
        if not self._ts_groups:
            return SignalResult(symbol=context.symbol, detail={"reason": "无时序规则组"})

        group_results: list[RuleResult] = []
        all_rule_results: list[RuleResult] = []

        for group in self._ts_groups:
            bindings = self._group_bindings.get(group.id, [])
            if not bindings:
                continue
            combined = self._evaluate_group(group, bindings, context)
            group_results.append(combined)
            all_rule_results.extend(combined.detail.get("sub_results_detail", []))

        if not group_results:
            return SignalResult(symbol=context.symbol)

        direction, strength = self._aggregate_groups(group_results)
        return SignalResult(
            symbol=context.symbol,
            direction=direction,
            strength=strength,
            confidence=strength,
            rule_results=all_rule_results,
            detail={
                "strategy_id": self.strategy_id,
                "signal_date": str(context.signal_date),
                "group_count": len(group_results),
            },
        )

    async def evaluate_symbol_async(
        self,
        symbol: str,
        signal_date: date,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    ) -> SignalResult:
        """异步包装 — 自动加载因子数据后调用同步核心。

        供模拟盘/实盘决策流调用。backtrader 内请直接调用 evaluate_symbol()。
        """
        factor_values, factor_series = await self._load_factor_series(
            symbol, signal_date, lookback_days,
        )
        context = RuleContext(
            symbol=symbol,
            signal_date=signal_date,
            factor_values=factor_values,
            factor_series=factor_series,
        )
        return self.evaluate_symbol(context)

    async def evaluate_universe_async(
        self,
        symbols: list[str],
        signal_date: date,
    ) -> dict[str, SignalResult]:
        """批量评估 universe 内所有标的的时序信号。"""
        results: dict[str, SignalResult] = {}
        for symbol in symbols:
            try:
                results[symbol] = await self.evaluate_symbol_async(symbol, signal_date)
            except Exception as e:
                logger.error(
                    f"时序信号评估异常: symbol={symbol} date={signal_date} error={e}",
                    exc_info=True,
                )
                results[symbol] = SignalResult(symbol=symbol, detail={"error": str(e)})
        return results

    def _evaluate_group(
        self,
        group: StrategyRuleGroup,
        bindings: list[StrategyRuleBinding],
        context: RuleContext,
    ) -> RuleResult:
        """评估单个规则组内所有规则并组合。"""
        rule_results: list[RuleResult] = []
        for binding in sorted(bindings, key=lambda b: b.sort_order):
            rule = self._rule_registry.get(binding.rule_id)
            ctx = RuleContext(
                symbol=context.symbol,
                signal_date=context.signal_date,
                factor_values=context.factor_values,
                factor_series=context.factor_series,
                cross_section_df=context.cross_section_df,
                config={**(binding.config_override or {})},
            )
            try:
                result = rule.evaluate(ctx)
                rule_results.append(result)
            except (KeyError, ValueError) as e:
                logger.warning(
                    f"规则评估异常: rule={binding.rule_id} symbol={context.symbol} error={e}"
                )
                rule_results.append(RuleResult(
                    rule_id=binding.rule_id, passed=False, detail={"error": str(e)},
                ))

        weights = {b.rule_id: b.weight for b in bindings if b.weight is not None}
        combination = _COMBINATION_STRATEGIES.get(
            group.combination_method, _DEFAULT_COMBINATION,
        )
        combined = combination.combine(
            rule_results, weights, group.combination_params or {},
        )
        combined.detail["sub_results_detail"] = rule_results
        return combined

    @staticmethod
    def _aggregate_groups(group_results: list[RuleResult]) -> tuple[str, float]:
        """聚合多个规则组结果 — AND 逻辑：方向一致取之，否则 neutral。"""
        if not group_results:
            return "neutral", 0.0

        non_neutral = [r for r in group_results if r.direction != "neutral"]
        if not non_neutral:
            return "neutral", 0.0

        directions = {r.direction for r in non_neutral}
        if len(directions) > 1:
            return "neutral", 0.0

        direction = directions.pop()
        strength = sum(r.confidence for r in group_results) / len(group_results)
        return direction, min(strength, 1.0)

    async def _load_factor_series(
        self,
        symbol: str,
        signal_date: date,
        lookback_days: int,
    ) -> tuple[dict[str, float], dict[str, pd.Series]]:
        """加载因子时序数据，返回 (当日因子值, 因子时序)。"""
        if not self._factor_ids:
            return {}, {}

        from xqtrader.domain.factor.models.factor_value import FacFactorValue

        start_date = signal_date - timedelta(days=lookback_days * 2)
        records = await FacFactorValue.filter(
            trade_date__gte=start_date,
            trade_date__lte=signal_date,
            pool_id="all",
            factor_id__in=self._factor_ids,
            symbol=symbol,
        )

        if not records:
            return {}, {}

        rows = [
            {"trade_date": r.trade_date, "factor_id": r.factor_id, "value": r.factor_value}
            for r in records if r.factor_value is not None
        ]
        if not rows:
            return {}, {}

        df = pd.DataFrame(rows)
        df = df.pivot_table(
            index="trade_date", columns="factor_id", values="value", aggfunc="first",
        ).sort_index()

        factor_series = {col: df[col].dropna() for col in df.columns}
        factor_values: dict[str, float] = {}
        if not df.empty:
            latest = df.iloc[-1]
            factor_values = {str(k): float(v) for k, v in latest.items() if pd.notna(v)}
        return factor_values, factor_series

    async def _collect_factor_ids(
        self, bindings: list[StrategyRuleBinding],
    ) -> list[str]:
        """收集所有规则依赖的因子 ID（批量查询）。"""
        from ..models.rule import RuleRegistry as RuleRegistryModel

        rule_ids = list({b.rule_id for b in bindings})
        if not rule_ids:
            return []
        rule_models = await RuleRegistryModel.filter(rule_id__in=rule_ids)
        factor_ids: set[str] = set()
        for rule_model in rule_models:
            if rule_model.factors:
                factor_ids.update(rule_model.factors)
        return list(factor_ids)
