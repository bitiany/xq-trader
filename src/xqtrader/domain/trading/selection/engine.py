"""选股引擎 — 编排层，高内聚低耦合，对上层保持 KISS 接口"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from framework.commons.logger import get_logger

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
from ..rules.expression.parser import parse_expression
from ..rules.registry import ExpressionRule, RuleRegistry

logger = get_logger(__name__)

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

# 财务指标表字段映射: factor_id → FinancialIndicator 字段
# 数据来源: stock.sdc_financial_indicator (季频财务指标)
# 文档参考: docs/factor-catalog.md B2-B5 基本面因子
# 注意: gross_margin 是"毛利"(绝对值), grossprofit_margin 才是"销售毛利率"(百分比)
# 选股策略中的 roe 阈值通常表达年化 ROE，优先使用 Tushare 的 roe_yearly 口径。
_FINANCIAL_INDICATOR_FIELD_MAP: dict[str, str] = {
    "roe": "roe_yearly",
    "roe_yearly": "roe_yearly",
    "roe_waa": "roe_waa",
    "roe_dt": "roe_dt",
    "roa": "roa",
    "roic": "roic",
    "grossprofit_margin": "grossprofit_margin",
    "netprofit_margin": "netprofit_margin",
    "debt_to_assets": "debt_to_assets",
    "current_ratio": "current_ratio",
    "quick_ratio": "quick_ratio",
    "bps": "bps",
    "eps": "eps",
    "dt_eps": "dt_eps",
    "assets_turn": "assets_turn",
    "inv_turn": "inv_turn",
    "ar_turn": "ar_turn",
    "ocf_to_profit": "ocf_to_profit",
    "ocf_to_or": "ocf_to_or",
    "dtprofit_to_profit": "dtprofit_to_profit",
    "ebit_to_interest": "ebit_to_interest",
    "ocf_to_debt": "ocf_to_debt",
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

        # 5. 加载全部截面规则绑定
        group_bindings: dict[int, list[StrategyRuleBinding]] = {}
        all_bindings: list[StrategyRuleBinding] = []
        for group in cs_groups:
            bindings = await StrategyRuleBinding.filter(group_id=group.id)
            if not bindings:
                logger.warning(f"规则组无绑定规则: {group.id}")
                continue
            group_bindings[group.id] = bindings
            all_bindings.extend(bindings)
        if not all_bindings:
            return {}

        # 6. 收集所有依赖因子
        factor_ids = await self._collect_factor_ids(all_bindings)
        self._ensure_direction_factors(factor_ids)

        # 7. 加载截面因子数据（含每日指标聚合）
        # 因子数据统一存储在 pool_id='all'（Task1 逐标的因子产出）
        # strategy.universe_pool 仅用于定义候选标的范围（由 UniverseProvider 处理）
        cross_section_df = await self._load_cross_section_data(
            symbols, factor_ids, signal_date, "all",
        )

        if cross_section_df is None or cross_section_df.empty:
            logger.warning(f"截面因子数据为空: date={signal_date}")
            return {}

        # 8. 注册规则（从 DB 加载或使用已注册的）
        await self._ensure_rules_registered(all_bindings)

        # 9. 逐规则执行截面评估
        all_rule_results: dict[str, pd.Series] = {}
        for binding in all_bindings:
            rule = self._rule_registry.get(binding.rule_id)
            if isinstance(rule, ExpressionRule):
                series_result = self._evaluate_expression_cross_section(
                    rule, cross_section_df, binding.config_override or {},
                )
                all_rule_results[binding.rule_id] = series_result
            elif isinstance(rule, RulePlugin):
                series_result = await self._evaluate_plugin_cross_section(
                    rule, cross_section_df, signal_date, binding.config_override or {},
                )
                all_rule_results[binding.rule_id] = series_result

        # 10. 按规则组组合结果；多个规则组之间采用 AND 关系，最终分数取各组得分均值
        group_scores: list[pd.Series] = []
        group_pass_masks: list[pd.Series] = []
        group_pass_by_id: dict[int, pd.Series] = {}
        for group in cs_groups:
            bindings = group_bindings.get(group.id, [])
            rule_results = {
                b.rule_id: all_rule_results[b.rule_id]
                for b in bindings
                if b.rule_id in all_rule_results
            }
            if not rule_results:
                continue
            weights = {b.rule_id: b.weight for b in bindings if b.weight}
            combination = _COMBINATION_STRATEGIES.get(
                group.combination_method, WeightedScoreCombination(),
            )
            combined = self._combine_cross_section(
                rule_results, combination, weights,
                group.combination_params or {},
            )
            group_scores.append(combined)
            group_pass_mask = combined >= (group.threshold or 0.0)
            group_pass_masks.append(group_pass_mask)
            group_pass_by_id[group.id] = group_pass_mask
        if not group_scores:
            return {}

        final_score = pd.concat(group_scores, axis=1).mean(axis=1)
        final_pass = group_pass_masks[0]
        for mask in group_pass_masks[1:]:
            final_pass = final_pass & mask

        self.last_diagnostics = {
            "filter_steps": await self._build_filter_steps(
                universe_size=len(symbols),
                groups=cs_groups,
                group_bindings=group_bindings,
                rule_results=all_rule_results,
                group_pass_by_id=group_pass_by_id,
                final_pass=final_pass,
            )
        }

        # 11. 构建选股结果（含因子快照）
        results: dict[str, SelectionScore] = {}
        for symbol in final_score.index:
            score = float(final_score.loc[symbol])
            if bool(final_pass.loc[symbol]):
                factor_snapshot = self._extract_factor_snapshot(
                    symbol, cross_section_df, factor_ids,
                )
                results[symbol] = SelectionScore(
                    symbol=symbol,
                    score=score,
                    direction=self._infer_direction(factor_snapshot),
                    confidence=score,
                    detail={
                        "strategy_id": strategy_id,
                        "signal_date": str(signal_date),
                        "factor_values": factor_snapshot,
                    },
                )

        # 12. 落库
        await self._persist_results(strategy_id, signal_date, results)

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
        rule_results: dict[str, pd.Series],
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
                series = rule_results.get(binding.rule_id)
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
                    "pass_rate": pass_count / universe_size if universe_size else 0.0,
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
                    "pass_rate": pass_count / universe_size if universe_size else 0.0,
                })

        final_count = int(final_pass.sum())
        steps.append({
            "step_type": "final",
            "label": "最终入选",
            "count": final_count,
            "pass_rate": final_count / universe_size if universe_size else 0.0,
        })
        return steps

    def _evaluate_expression_cross_section(
        self,
        rule: ExpressionRule,
        cross_section_df: pd.DataFrame,
        config_override: dict[str, Any],
    ) -> pd.Series:
        """截面模式下求值表达式规则，返回 Series(index=symbol)"""
        try:
            ast = parse_expression(rule.expression)
            result = self._evaluator.evaluate(
                ast=ast,
                cross_section_df=cross_section_df,
            )
            # 布尔 Series → 数值 Series (True=1.0, False=0.0)
            if isinstance(result, pd.Series):
                return result.astype(float)
            return pd.Series(float(result), index=cross_section_df.index)
        except (KeyError, ValueError) as e:
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
    ) -> pd.Series:
        """组合截面规则结果，返回 Series(index=symbol, values=score)"""
        if not rule_results:
            return pd.Series(dtype=float)

        # 对每个标的，构建 RuleResult 列表并组合
        first_series = next(iter(rule_results.values()))
        symbols = first_series.index
        combined_scores = pd.Series(0.0, index=symbols)

        for symbol in symbols:
            per_symbol_results: list[RuleResult] = []
            for rule_id, series in rule_results.items():
                val = series.get(symbol, 0.0)
                if pd.isna(val):
                    val = 0.0
                passed = val > 0 if isinstance(val, float) else bool(val)
                per_symbol_results.append(RuleResult(
                    rule_id=rule_id,
                    passed=passed,
                    score=abs(val),
                    direction="long" if val > 0 else "neutral",
                    confidence=abs(val),
                ))
            combined = combination.combine(per_symbol_results, weights, params)
            combined_scores.loc[symbol] = combined.score

        return combined_scores

    @staticmethod
    def _ensure_direction_factors(factor_ids: list[str]) -> None:
        for factor_id in ("mom_20d", "barra_momentum"):
            if factor_id not in factor_ids:
                factor_ids.append(factor_id)

    @staticmethod
    def _infer_direction(factor_snapshot: dict[str, float]) -> str:
        for factor_id in ("mom_20d", "barra_momentum"):
            value = factor_snapshot.get(factor_id)
            if value is not None and value < 0:
                return "short"
        return "long"

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
        """收集所有规则依赖的因子 ID"""
        factor_ids: set[str] = set()
        for binding in bindings:
            rule_model = await RuleRegistryModel.get_or_none(rule_id=binding.rule_id)
            if rule_model and rule_model.factors:
                for fid in rule_model.factors:
                    factor_ids.add(fid)
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
        """
        from xqtrader.domain.market.models.financial_indicator import FinancialIndicator

        records = await FinancialIndicator.filter(
            symbol__in=symbols,
            end_date__lte=signal_date,
            order_by=FinancialIndicator.end_date.desc(),
        )

        if not records:
            return None

        # 每个 symbol 取最新一期（records 已按 end_date 倒序）
        seen: set[str] = set()
        rows: list[dict[str, Any]] = []
        for r in records:
            if r.symbol in seen:
                continue
            seen.add(r.symbol)
            row: dict[str, Any] = {"symbol": r.symbol}
            for fid in factor_ids:
                field = _FINANCIAL_INDICATOR_FIELD_MAP.get(fid)
                if field:
                    val = getattr(r, field, None)
                    if val is None and fid == "roe":
                        val = getattr(r, "roe", None)
                    if val is not None:
                        row[fid] = float(val)
            rows.append(row)

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df = df.groupby("symbol").agg("first").reset_index()
        return df.set_index("symbol")

    async def _ensure_rules_registered(self, bindings: list[StrategyRuleBinding]) -> None:
        """确保规则已注册到内存注册表"""
        for binding in bindings:
            if self._rule_registry.has(binding.rule_id):
                continue
            rule_model = await RuleRegistryModel.get_or_none(rule_id=binding.rule_id)
            if not rule_model:
                logger.warning(f"规则未找到: {binding.rule_id}")
                continue

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

    async def _persist_results(
        self,
        strategy_id: str,
        signal_date: date,
        results: dict[str, SelectionScore],
    ) -> None:
        """选股结果落库 — 含因子值快照

        幂等：同策略实例+信号日重复运行时，先删除旧记录再插入，避免重复。
        """
        strategy = await Strategy.get_or_none(strategy_id=strategy_id)
        if not strategy:
            return

        # 幂等：清除同策略实例+信号日的旧记录（研究域 instance_id=0）
        await SelectionResult.delete_many(instance_id=0, signal_date=signal_date)

        for rank, (symbol, score) in enumerate(
            sorted(results.items(), key=lambda x: x[1].score, reverse=True), start=1,
        ):
            await SelectionResult.create(
                instance_id=0,  # 研究域无 instance
                signal_date=signal_date,
                symbol=symbol,
                score=score.score,
                rank=rank,
                factor_values=score.detail,  # 含 factor_values 快照
            )
