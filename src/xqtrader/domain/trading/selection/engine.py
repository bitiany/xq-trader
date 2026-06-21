"""选股引擎 — 编排层，高内聚低耦合，对上层保持 KISS 接口"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from framework.commons.logger import get_logger
from framework.dal.transaction.transactional import transactional

from ..models.decision import SelectionResult
from ..models.rule import RuleRegistry as RuleRegistryModel
from ..models.strategy import Strategy, StrategyRuleBinding, StrategyRuleGroup
from ..rules.base import RuleContext, RulePlugin, RuleResult, SelectionScore, UniverseProvider
from ..rules.combination.and_or import AndCombination, OrCombination
from ..rules.combination.base import CombinationStrategy
from ..rules.combination.ic_weighted import ICWeightedCombination
from ..rules.combination.weighted_score import WeightedScoreCombination
from ..rules.combination.weighted_vote import WeightedVoteCombination
from ..rules.expression.evaluator import ExpressionEvaluator
from ..rules.registry import ExpressionRule, RuleRegistry

logger = get_logger(__name__)

# 默认因子池 ID（Task1 逐标的因子产出统一存储在 pool_id='all'）
_DEFAULT_POOL_ID = "all"

# 组合策略注册表
_COMBINATION_STRATEGIES: dict[str, CombinationStrategy] = {
    "and": AndCombination(),
    "or": OrCombination(),
    "weighted_score": WeightedScoreCombination(),
    "weighted_vote": WeightedVoteCombination(),
    "ic_weighted": ICWeightedCombination(),
}

# 每日指标表字段映射: factor_id → DailyIndicator 字段
# 数据来源: stock.sdc_daily_indicator (日频估值指标)
# 文档参考: docs/factor-catalog.md B1 价值因子
_DAILY_INDICATOR_FIELD_MAP: dict[str, str] = {
    "pe": "pe",
    "pe_ttm": "pe_ttm",
    "pb": "pb",
    "ps": "ps",
    "ps_ttm": "ps_ttm",
    "dv_ratio": "dv_ratio",
    "dv_ttm": "dv_ttm",
    "total_mv": "total_mv",
    "circ_mv": "circ_mv",
    "turnover_rate": "turnover_rate",
    "turnover_rate_f": "turnover_rate_f",
    "volume_ratio": "volume_ratio",
    "ev_ebitda": "ev_ebitda",
    "peg": "peg",
}

# 每日指标表衍生因子: factor_id → (原始字段, 转换函数)
# 这些因子需从原始字段计算转换，参考 docs/factor-catalog.md B1 价值因子
# ep_ttm = 1/pe_ttm (盈利收益率), bp = 1/pb (账面市值比), sp_ttm = 1/ps_ttm (销售收益率)
_DAILY_INDICATOR_DERIVED_MAP: dict[str, tuple[str, str]] = {
    "ep": ("pe_ttm", "inverse"),
    "ep_ttm": ("pe_ttm", "inverse"),
    "bp": ("pb", "inverse"),
    "sp_ttm": ("ps_ttm", "inverse"),
}

# 财务指标表字段映射: factor_id → FinancialIndicator 字段（支持回退链，前者优先）
# 数据来源: stock.sdc_financial_indicator (季频财务指标)
# 文档参考: docs/factor-catalog.md B2-B5 基本面因子
# 注意: gross_margin 是"毛利"(绝对值), grossprofit_margin 才是"销售毛利率"(百分比)
# 选股策略中的 roe 阈值通常表达年化 ROE，优先使用 roe_yearly，回退到 roe。
_FINANCIAL_INDICATOR_FIELD_MAP: dict[str, tuple[str, ...]] = {
    "roe": ("roe_yearly", "roe"),
    "roe_yearly": ("roe_yearly",),
    "roe_waa": ("roe_waa",),
    "roe_dt": ("roe_dt",),
    "roa": ("roa",),
    "roic": ("roic",),
    "grossprofit_margin": ("grossprofit_margin",),
    "netprofit_margin": ("netprofit_margin",),
    "debt_to_assets": ("debt_to_assets",),
    "current_ratio": ("current_ratio",),
    "quick_ratio": ("quick_ratio",),
    "bps": ("bps",),
    "eps": ("eps",),
    "dt_eps": ("dt_eps",),
    "assets_turn": ("assets_turn",),
    "inv_turn": ("inv_turn",),
    "ar_turn": ("ar_turn",),
    "ocf_to_profit": ("ocf_to_profit",),
    "ocf_to_or": ("ocf_to_or",),
    "dtprofit_to_profit": ("dtprofit_to_profit",),
    "ebit_to_interest": ("ebit_to_interest",),
    "ocf_to_debt": ("ocf_to_debt",),
}


class SelectionEngine:
    """选股引擎 — 从候选池中筛选标的

    对上层暴露简洁接口:
        engine = SelectionEngine()
        results = await engine.run(strategy_id, signal_date, universe)

    支持两种场景:
        1. 研究域: universe=IndexUniverse("idx_300") → 全市场/指数选股
        2. 实盘域: universe=WatchlistUniverse(instance_id) → 自选池选股
    """

    def __init__(self) -> None:
        self._rule_registry = RuleRegistry()
        self._evaluator = ExpressionEvaluator()
        self.last_diagnostics: dict[str, Any] = {}

    async def run(
        self,
        strategy_id: str,
        signal_date: date,
        universe: UniverseProvider,
    ) -> dict[str, SelectionScore]:
        """执行选股

        Args:
            strategy_id: 策略编码（对应 td_strategy.strategy_id）
            signal_date: 信号日期
            universe: 候选标的提供者

        Returns:
            {symbol: SelectionScore} 入选标的及其得分
        """
        # 1. 加载策略配置
        strategy = await Strategy.get_or_none(strategy_id=strategy_id)
        if not strategy:
            msg = f"策略不存在: {strategy_id}"
            raise ValueError(msg)

        self.last_diagnostics = {}

        # 2. 获取候选标的
        symbols = await universe.get_symbols()
        if not symbols:
            logger.info(f"SelectionEngine | 候选池为空: {universe.describe()}")
            return {}

        logger.info(
            f"SelectionEngine | strategy={strategy_id} | "
            f"date={signal_date} | universe={universe.describe()} | "
            f"symbols={len(symbols)}"
        )

        # 3. 加载策略规则组
        rule_groups = await StrategyRuleGroup.filter(strategy_id=strategy.id)
        if not rule_groups:
            logger.warning(f"策略无规则组: {strategy_id}")
            return {}

        # 4. 加载截面规则组：组内按 combination_method，多个截面规则组之间按 AND 关系
        cs_groups = [g for g in rule_groups if g.group_type == "cross_section"]
        if not cs_groups:
            logger.warning(f"策略无截面规则组: {strategy_id}")
            return {}

        # 5. 批量加载全部截面规则绑定（避免 N+1 查询）
        all_bindings = await StrategyRuleBinding.filter(
            group_id__in=[g.id for g in cs_groups],
            order_by=StrategyRuleBinding.group_id,
        )
        group_bindings: dict[int, list[StrategyRuleBinding]] = {}
        for binding in all_bindings:
            group_bindings.setdefault(binding.group_id, []).append(binding)
        for group in cs_groups:
            if group.id not in group_bindings:
                logger.warning(f"规则组无绑定规则: {group.id}")
        if not all_bindings:
            return {}

        # 6. 收集所有依赖因子
        exclude_short = self._get_exclude_short(strategy)
        factor_ids = await self._collect_factor_ids(all_bindings)

        # 7. 加载截面因子数据（含每日指标聚合）
        # 因子数据统一存储在 pool_id='all'（Task1 逐标的因子产出）
        # strategy.universe_pool 仅用于定义候选标的范围（由 UniverseProvider 处理）
        cross_section_df = await self._load_cross_section_data(
            symbols, factor_ids, signal_date, _DEFAULT_POOL_ID,
        )

        if cross_section_df is None or cross_section_df.empty:
            logger.warning(f"截面因子数据为空: date={signal_date}")
            return {}

        # 8. 注册规则（批量从 DB 加载）
        await self._ensure_rules_registered(all_bindings)

        # 9. 逐绑定执行截面评估
        # 以 binding.id 为键，避免同一 rule_id 在多 group 中以不同 config_override 出现时结果被覆盖
        binding_results: dict[int, pd.Series] = {}
        for binding in all_bindings:
            rule = self._rule_registry.get(binding.rule_id)
            if isinstance(rule, ExpressionRule):
                binding_results[binding.id] = self._evaluate_expression_cross_section(
                    rule, cross_section_df, binding.config_override or {},
                )
            elif isinstance(rule, RulePlugin):
                binding_results[binding.id] = await self._evaluate_plugin_cross_section(
                    rule, cross_section_df, signal_date, binding.config_override or {},
                )
            else:
                logger.warning(f"未知规则类型: rule_id={binding.rule_id}")

        # 10. 按规则组组合结果；多个规则组之间采用 AND 关系，最终分数取各组得分均值
        group_scores: list[pd.Series] = []
        group_directions: list[pd.Series] = []
        group_pass_masks: list[pd.Series] = []
        group_pass_by_id: dict[int, pd.Series] = {}
        for group in cs_groups:
            bindings = group_bindings.get(group.id, [])
            rule_results = {
                b.rule_id: binding_results[b.id]
                for b in bindings
                if b.id in binding_results
            }
            if not rule_results:
                continue
            weights = {b.rule_id: b.weight for b in bindings if b.weight is not None}
            combination = _COMBINATION_STRATEGIES.get(
                group.combination_method, WeightedScoreCombination(),
            )
            combined_scores, combined_directions = self._combine_cross_section(
                rule_results, combination, weights,
                group.combination_params or {},
            )
            group_scores.append(combined_scores)
            group_directions.append(combined_directions)
            group_pass_mask = combined_scores >= (group.threshold or 0.0)
            group_pass_masks.append(group_pass_mask)
            group_pass_by_id[group.id] = group_pass_mask
        if not group_scores:
            return {}

        # 各组得分均值 — skipna=False 要求所有组都有得分，避免部分组缺失时得分虚高
        final_score = pd.concat(group_scores, axis=1).mean(axis=1, skipna=False)
        final_pass = group_pass_masks[0]
        for mask in group_pass_masks[1:]:
            final_pass = final_pass & mask
        # 聚合各组方向（取首个非 neutral，全 neutral 默认 long）
        final_direction = self._aggregate_directions(group_directions, final_score.index)

        self.last_diagnostics = {
            "filter_steps": await self._build_filter_steps(
                universe_size=len(symbols),
                groups=cs_groups,
                group_bindings=group_bindings,
                binding_results=binding_results,
                group_pass_by_id=group_pass_by_id,
                final_pass=final_pass,
            )
        }

        # 11. 构建选股结果（含因子快照）；按策略配置决定是否排除空头标的
        results: dict[str, SelectionScore] = {}
        for symbol in final_score.index:
            score = float(final_score.loc[symbol])
            if not bool(final_pass.loc[symbol]):
                continue
            direction = str(final_direction.loc[symbol])
            if direction == "short" and exclude_short:
                continue
            factor_snapshot = self._extract_factor_snapshot(
                symbol, cross_section_df, factor_ids,
            )
            results[symbol] = SelectionScore(
                symbol=symbol,
                score=score,
                direction=direction,
                confidence=score,
                detail={
                    "strategy_id": strategy_id,
                    "signal_date": str(signal_date),
                    "factor_values": factor_snapshot,
                },
            )

        # 12. 落库（instance_id 由 universe 提供，研究域=0，实盘域=真实 instance_id）
        await self._persist_results(strategy, universe.instance_id, signal_date, results)

        logger.info(
            f"SelectionEngine | strategy={strategy_id} | "
            f"selected={len(results)}/{len(symbols)} | "
            f"cross_section_groups={len(cs_groups)}"
        )
        return results

    async def _build_filter_steps(
        self,
        universe_size: int,
        groups: list[StrategyRuleGroup],
        group_bindings: dict[int, list[StrategyRuleBinding]],
        binding_results: dict[int, pd.Series],
        group_pass_by_id: dict[int, pd.Series],
        final_pass: pd.Series,
    ) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = [{
            "step_type": "universe",
            "label": "候选池",
            "count": universe_size,
            "pass_rate": 1.0,
        }]
        rule_ids = [b.rule_id for bindings in group_bindings.values() for b in bindings]
        rule_models = await RuleRegistryModel.filter(rule_id__in=rule_ids) if rule_ids else []
        rule_map = {r.rule_id: r for r in rule_models}

        for group in groups:
            bindings = sorted(
                group_bindings.get(group.id, []),
                key=lambda b: b.sort_order,
            )
            for binding in bindings:
                series = binding_results.get(binding.id)
                if series is None:
                    continue
                pass_count = int((series > 0).sum())
                rule_model = rule_map.get(binding.rule_id)
                steps.append({
                    "step_type": "rule",
                    "group_id": group.id,
                    "group_method": group.combination_method,
                    "rule_id": binding.rule_id,
                    "label": rule_model.name if rule_model else binding.rule_id,
                    "expression": rule_model.expression if rule_model else None,
                    "spi_class": rule_model.spi_class if rule_model else None,
                    "factors": rule_model.factors if rule_model else [],
                    "weight": binding.weight,
                    "count": pass_count,
                    "pass_rate": self._pass_rate(pass_count, universe_size),
                })
            group_mask = group_pass_by_id.get(group.id)
            if group_mask is not None:
                pass_count = int(group_mask.sum())
                steps.append({
                    "step_type": "group",
                    "group_id": group.id,
                    "group_method": group.combination_method,
                    "label": f"规则组通过({group.combination_method})",
                    "threshold": group.threshold,
                    "count": pass_count,
                    "pass_rate": self._pass_rate(pass_count, universe_size),
                })

        final_count = int(final_pass.sum())
        steps.append({
            "step_type": "final",
            "label": "最终入选",
            "count": final_count,
            "pass_rate": self._pass_rate(final_count, universe_size),
        })
        return steps

    @staticmethod
    def _pass_rate(pass_count: int, universe_size: int) -> float:
        return pass_count / universe_size if universe_size else 0.0

    def _evaluate_expression_cross_section(
        self,
        rule: ExpressionRule,
        cross_section_df: pd.DataFrame,
        config_override: dict[str, Any],
    ) -> pd.Series:
        """截面模式下求值表达式规则，返回 Series(index=symbol)"""
        try:
            ast = rule.get_ast()
            result = self._evaluator.evaluate(
                ast=ast,
                cross_section_df=cross_section_df,
            )
            # 布尔 Series → 数值 Series (True=1.0, False=0.0)
            if isinstance(result, pd.Series):
                return result.astype(float)
            return pd.Series(float(result), index=cross_section_df.index)
        except (KeyError, ValueError, SyntaxError) as e:
            logger.warning(f"截面表达式求值异常: rule={rule.rule_id} error={e}")
            return pd.Series(0.0, index=cross_section_df.index)

    async def _evaluate_plugin_cross_section(
        self,
        rule: RulePlugin,
        cross_section_df: pd.DataFrame,
        signal_date: date,
        config_override: dict[str, Any],
    ) -> pd.Series:
        """截面模式下求值 SPI 插件规则，返回 Series(index=symbol)。"""
        scores = pd.Series(0.0, index=cross_section_df.index)
        for symbol in cross_section_df.index:
            factor_values = {
                col: float(value)
                for col, value in cross_section_df.loc[symbol].items()
                if pd.notna(value)
            }
            result = await rule.evaluate(RuleContext(
                symbol=symbol,
                signal_date=signal_date,
                factor_values=factor_values,
                cross_section_df=cross_section_df,
                config=config_override,
            ))
            scores.loc[symbol] = result.score if result.passed else 0.0
        return scores

    def _combine_cross_section(
        self,
        rule_results: dict[str, pd.Series],
        combination: CombinationStrategy,
        weights: dict[str, float],
        params: dict[str, Any],
    ) -> tuple[pd.Series, pd.Series]:
        """组合截面规则结果

        Returns:
            (scores, directions) — 均为 Series(index=symbol)
            scores: 组合得分
            directions: 组合方向 (long/short/neutral)
        """
        if not rule_results:
            return pd.Series(dtype=float), pd.Series(dtype=str)

        # 对每个标的，构建 RuleResult 列表并组合
        first_series = next(iter(rule_results.values()))
        symbols = first_series.index
        combined_scores = pd.Series(0.0, index=symbols)
        combined_directions = pd.Series("neutral", index=symbols, dtype=str)

        for symbol in symbols:
            per_symbol_results: list[RuleResult] = []
            for rule_id, series in rule_results.items():
                val = series.get(symbol, 0.0)
                if pd.isna(val):
                    val = 0.0
                passed = val > 0
                per_symbol_results.append(RuleResult(
                    rule_id=rule_id,
                    passed=passed,
                    score=abs(val),
                    direction="long" if val > 0 else ("short" if val < 0 else "neutral"),
                    confidence=abs(val),
                ))
            combined = combination.combine(per_symbol_results, weights, params)
            combined_scores.loc[symbol] = combined.score
            combined_directions.loc[symbol] = combined.direction

        return combined_scores, combined_directions

    @staticmethod
    def _get_exclude_short(strategy: Strategy) -> bool:
        """从策略 cross_section_config 读取是否排除空头标的"""
        config = strategy.cross_section_config or {}
        return bool(config.get("exclude_short", False))

    @staticmethod
    def _aggregate_directions(
        group_directions: list[pd.Series], symbols: pd.Index,
    ) -> pd.Series:
        """聚合多个规则组的方向 — 取首个非 neutral 方向，全 neutral 则默认 long"""
        result = pd.Series("long", index=symbols, dtype=str)
        for symbol in symbols:
            for directions in group_directions:
                d = directions.get(symbol, "neutral")
                if d != "neutral":
                    result.loc[symbol] = d
                    break
        return result

    def _extract_factor_snapshot(
        self,
        symbol: str,
        cross_section_df: pd.DataFrame,
        factor_ids: list[str],
    ) -> dict[str, float]:
        """提取单个标的的因子值快照"""
        if symbol not in cross_section_df.index:
            return {}
        row = cross_section_df.loc[symbol]
        snapshot: dict[str, float] = {}
        for fid in factor_ids:
            if fid in row.index:
                val = row[fid]
                if pd.notna(val):
                    snapshot[fid] = float(val)
        return snapshot

    async def _collect_factor_ids(self, bindings: list[StrategyRuleBinding]) -> list[str]:
        """收集所有规则依赖的因子 ID（批量查询，避免 N+1）"""
        rule_ids = list({b.rule_id for b in bindings})
        if not rule_ids:
            return []
        rule_models = await RuleRegistryModel.filter(rule_id__in=rule_ids)
        factor_ids: set[str] = set()
        for rule_model in rule_models:
            if rule_model.factors:
                factor_ids.update(rule_model.factors)
        return list(factor_ids)

    async def _load_cross_section_data(
        self,
        symbols: list[str],
        factor_ids: list[str],
        signal_date: date,
        pool_id: str,
    ) -> pd.DataFrame | None:
        """加载截面因子数据

        数据来源（参考 docs/factor-architecture.md 5.1）:
        1. stock.fac_factor_value — 逐标的因子（技术/量价/资金流，Task1 产出）
        2. stock.sdc_daily_indicator — 每日估值指标（pe/pb/ps 等，日频）
        3. stock.sdc_financial_indicator — 财务指标（roe/grossprofit_margin 等，季频 PIT）
        """
        if not factor_ids:
            return None

        # 区分因子来源
        # 衍生因子（ep/bp 等）依赖每日指标表原始字段，归入 di 组
        fv_factor_ids = [
            fid for fid in factor_ids
            if fid not in _DAILY_INDICATOR_FIELD_MAP
            and fid not in _FINANCIAL_INDICATOR_FIELD_MAP
            and fid not in _DAILY_INDICATOR_DERIVED_MAP
        ]
        di_factor_ids = [
            fid for fid in factor_ids
            if fid in _DAILY_INDICATOR_FIELD_MAP or fid in _DAILY_INDICATOR_DERIVED_MAP
        ]
        fi_factor_ids = [
            fid for fid in factor_ids if fid in _FINANCIAL_INDICATOR_FIELD_MAP
        ]

        dfs: list[pd.DataFrame] = []

        # 1. 加载因子规格表数据
        if fv_factor_ids:
            df = await self._load_factor_value_data(symbols, fv_factor_ids, signal_date, pool_id)
            if df is not None:
                dfs.append(df)

        # 2. 加载每日指标表数据（含衍生因子转换）
        if di_factor_ids:
            df = await self._load_daily_indicator_data(symbols, di_factor_ids, signal_date)
            if df is not None:
                dfs.append(df)

        # 3. 加载财务指标表数据
        if fi_factor_ids:
            df = await self._load_financial_indicator_data(symbols, fi_factor_ids, signal_date)
            if df is not None:
                dfs.append(df)

        if not dfs:
            return None

        # 合并所有数据源
        result = dfs[0]
        for df in dfs[1:]:
            result = result.join(df, how="outer")

        # 仅保留请求的标的
        result = result[result.index.isin(symbols)]
        return result if not result.empty else None

    async def _load_factor_value_data(
        self,
        symbols: list[str],
        factor_ids: list[str],
        signal_date: date,
        pool_id: str,
    ) -> pd.DataFrame | None:
        """从 fac_factor_value 加载因子数据"""
        from xqtrader.domain.factor.models.factor_value import FacFactorValue

        records = await FacFactorValue.filter(
            trade_date=signal_date,
            pool_id=pool_id,
            factor_id__in=factor_ids,
            symbol__in=symbols,
        )

        if not records:
            return None

        rows = [
            {"symbol": r.symbol, r.factor_id: r.factor_value}
            for r in records
            if r.factor_value is not None
        ]
        if not rows:
            return None

        df = pd.DataFrame(rows)
        df = df.groupby("symbol").agg("first").reset_index()
        return df.set_index("symbol")

    async def _load_daily_indicator_data(
        self,
        symbols: list[str],
        factor_ids: list[str],
        signal_date: date,
    ) -> pd.DataFrame | None:
        """从 sdc_daily_indicator 加载估值指标数据

        支持直接字段映射（pe_ttm/pb 等）和衍生因子转换（ep=1/pe_ttm, bp=1/pb 等）。
        衍生因子定义参考 docs/factor-catalog.md B1 价值因子。
        """
        from xqtrader.domain.market.models.daily_indicator import DailyIndicator

        records = await DailyIndicator.filter(
            trade_date=signal_date,
            symbol__in=symbols,
        )

        if not records:
            return None

        # 收集衍生因子所需的原始字段
        derived_raw_fields: set[str] = set()
        for fid in factor_ids:
            if fid in _DAILY_INDICATOR_DERIVED_MAP:
                derived_raw_fields.add(_DAILY_INDICATOR_DERIVED_MAP[fid][0])

        # 映射 factor_id → DailyIndicator 字段
        rows: list[dict[str, Any]] = []
        for r in records:
            row: dict[str, Any] = {"symbol": r.symbol}
            # 直接字段映射
            for fid in factor_ids:
                field = _DAILY_INDICATOR_FIELD_MAP.get(fid)
                if field:
                    val = getattr(r, field, None)
                    if val is not None:
                        row[fid] = float(val)
            # 衍生因子转换（ep=1/pe_ttm, bp=1/pb, sp_ttm=1/ps_ttm）
            for fid in factor_ids:
                if fid in _DAILY_INDICATOR_DERIVED_MAP:
                    raw_field, transform = _DAILY_INDICATOR_DERIVED_MAP[fid]
                    raw_val = getattr(r, raw_field, None)
                    if raw_val is not None and transform == "inverse" and float(raw_val) > 0:
                        row[fid] = 1.0 / float(raw_val)
            rows.append(row)

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df = df.groupby("symbol").agg("first").reset_index()
        return df.set_index("symbol")

    async def _load_financial_indicator_data(
        self,
        symbols: list[str],
        factor_ids: list[str],
        signal_date: date,
    ) -> pd.DataFrame | None:
        """从 sdc_financial_indicator 加载财务指标数据

        季度因子截面补全策略:
        - 按报告期 end_date 向前找最近一期季度因子
        - 例如 03-31 之后的交易日使用 03-31 这期季度因子，直到下一期报告期出现
        - 每个 symbol 取 end_date <= signal_date 的最新一条记录
        - 使用子查询 MAX(end_date) GROUP BY symbol 避免加载全量历史
        """
        from sqlalchemy import and_, func, select

        from xqtrader.domain.market.models.financial_indicator import FinancialIndicator

        # 子查询: 每个 symbol 在 signal_date 之前的最新 end_date（仅取最新修订 update_flag='1'）
        subq = (
            select(
                FinancialIndicator.symbol,
                func.max(FinancialIndicator.end_date).label("max_end_date"),
            )
            .where(
                FinancialIndicator.symbol.in_(symbols),
                FinancialIndicator.end_date <= signal_date,
                FinancialIndicator.update_flag == "1",
            )
            .group_by(FinancialIndicator.symbol)
            .subquery()
        )

        # 主查询: JOIN 子查询取每个 symbol 最新一期完整记录
        stmt = (
            select(FinancialIndicator)
            .join(
                subq,
                and_(
                    FinancialIndicator.symbol == subq.c.symbol,
                    FinancialIndicator.end_date == subq.c.max_end_date,
                ),
            )
        )

        async with FinancialIndicator._get_engines_manager().get_transaction_session(
            FinancialIndicator._get_bind_key(),
        ) as db:
            result = await db.execute(stmt)
            records = list(result.scalars().all())

        if not records:
            return None

        rows: list[dict[str, Any]] = []
        for r in records:
            row: dict[str, Any] = {"symbol": r.symbol}
            for fid in factor_ids:
                field_chain = _FINANCIAL_INDICATOR_FIELD_MAP.get(fid)
                if not field_chain:
                    continue
                # 按回退链顺序取第一个非空值
                for field in field_chain:
                    val = getattr(r, field, None)
                    if val is not None:
                        row[fid] = float(val)
                        break
            rows.append(row)

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df = df.groupby("symbol").agg("first").reset_index()
        return df.set_index("symbol")

    async def _ensure_rules_registered(self, bindings: list[StrategyRuleBinding]) -> None:
        """确保规则已注册到内存注册表（批量查询，避免 N+1）"""
        # 收集未注册的 rule_id
        missing_rule_ids = list({
            b.rule_id for b in bindings if not self._rule_registry.has(b.rule_id)
        })
        if not missing_rule_ids:
            return

        rule_models = await RuleRegistryModel.filter(rule_id__in=missing_rule_ids)
        found_ids = {r.rule_id for r in rule_models}

        for rule_id in missing_rule_ids:
            if rule_id not in found_ids:
                logger.warning(f"规则未找到: {rule_id}")

        for rule_model in rule_models:
            if rule_model.type == "expression":
                self._rule_registry.register_expression(
                    rule_id=rule_model.rule_id,
                    name=rule_model.name,
                    category=rule_model.category,
                    expression=rule_model.expression or "",
                    signal_mapping=rule_model.signal_mapping or {},
                    default_config=rule_model.default_config or {},
                )
            elif rule_model.type == "spi" and rule_model.spi_class:
                self._load_spi_plugin(rule_model.spi_class)

    def _load_spi_plugin(self, spi_class_path: str) -> None:
        """动态加载 SPI 插件"""
        import importlib

        try:
            module_path, class_name = spi_class_path.rsplit(".", 1)
            module = importlib.import_module(module_path)
            plugin_class = getattr(module, class_name)
            plugin = plugin_class()
            self._rule_registry.register_plugin(plugin)
        except (ImportError, AttributeError) as e:
            logger.error(f"SPI 插件加载失败: {spi_class_path} error={e}", exc_info=True)

    @transactional(bind_key="trading")
    async def _persist_results(
        self,
        strategy: Strategy,
        instance_id: int,
        signal_date: date,
        results: dict[str, SelectionScore],
    ) -> None:
        """选股结果落库 — 含因子值快照

        幂等：同策略+实例+信号日重复运行时，先删除旧记录再批量插入，避免重复。
        instance_id 由调用方传入：研究域=0，实盘域=真实 instance_id。
        strategy_id 用于区分研究域同日运行的不同策略。
        """
        # 幂等：清除同策略+实例+信号日的旧记录
        await SelectionResult.delete_many(
            instance_id=instance_id,
            strategy_id=strategy.strategy_id,
            signal_date=signal_date,
        )

        if not results:
            return

        # 批量构建 + upsert（on_conflict 使用自然键，兜底防重复）
        instances = [
            SelectionResult(
                instance_id=instance_id,
                strategy_id=strategy.strategy_id,
                signal_date=signal_date,
                symbol=symbol,
                score=score.score,
                rank=rank,
                factor_values=score.detail.get("factor_values", {}),
            )
            for rank, (symbol, score) in enumerate(
                sorted(results.items(), key=lambda x: x[1].score, reverse=True),
                start=1,
            )
        ]
        await SelectionResult.bulk_create_or_update(
            instances,
            on_conflict=["instance_id", "strategy_id", "signal_date", "symbol"],
            update_fields=["score", "rank", "factor_values"],
        )
