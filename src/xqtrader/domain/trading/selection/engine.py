"""选股引擎 — 从候选池中筛选标的

对上层暴露简洁接口:
    engine = SelectionEngine()
    results = await engine.run(strategy_id, signal_date, universe)

流程:
  1. 从 DB 加载策略配置（Strategy）
  2. 解析 config JSONB → 规则组 + 融合配置
  3. 加载候选标的因子数据（截面 DataFrame）
  4. 逐规则求值得分 Series，逐组用 FusionEngine 融合
  5. 组间融合 → 最终结果
  6. 落库

设计:
  - 配置与运行态严格分离：策略配置不含标的/日期/资金
  - 方向语义：bullish/bearish/neutral（截面方向）
  - 截面引擎独立于时序回测引擎，仅在工作流层串联
"""

from __future__ import annotations

from collections import defaultdict  # noqa: F401
from datetime import date
from typing import Any

import pandas as pd

from framework.commons.logger import get_logger
from framework.dal.transaction.transactional import transactional

from ..backtest.core import FusionConfig, RuleResult
from ..backtest.fusion import FusionEngine
from ..enums import RuleDirection
from ..models.decision import SelectionResult
from ..models.rule import RuleRegistry as RuleRegistryModel
from ..models.strategy import Strategy
from ..rules.base import UniverseProvider
from ..rules.expression.evaluator import ExpressionEvaluator
from ..rules.expression.parser import parse_expression

logger = get_logger(__name__)


# 默认因子池 ID（Task1 逐标的因子产出统一存储在 pool_id='all'）
_DEFAULT_POOL_ID = "all"

# 每日指标表字段映射: factor_id → DailyIndicator 字段
_DAILY_INDICATOR_FIELD_MAP: dict[str, str] = {
    "pe": "pe", "pe_ttm": "pe_ttm", "pb": "pb", "ps": "ps",
    "ps_ttm": "ps_ttm", "dv_ratio": "dv_ratio", "dv_ttm": "dv_ttm",
    "total_mv": "total_mv", "circ_mv": "circ_mv",
    "turnover_rate": "turnover_rate", "turnover_rate_f": "turnover_rate_f",
    "volume_ratio": "volume_ratio", "ev_ebitda": "ev_ebitda", "peg": "peg",
}

_DAILY_INDICATOR_DERIVED_MAP: dict[str, tuple[str, str]] = {
    "ep": ("pe_ttm", "inverse"), "ep_ttm": ("pe_ttm", "inverse"),
    "bp": ("pb", "inverse"), "sp_ttm": ("ps_ttm", "inverse"),
}

_FINANCIAL_INDICATOR_FIELD_MAP: dict[str, tuple[str, ...]] = {
    "roe": ("roe_yearly", "roe"), "roe_yearly": ("roe_yearly",),
    "roe_waa": ("roe_waa",), "roe_dt": ("roe_dt",),
    "roa": ("roa",), "roic": ("roic",),
    "grossprofit_margin": ("grossprofit_margin",),
    "netprofit_margin": ("netprofit_margin",),
    "debt_to_assets": ("debt_to_assets",),
    "current_ratio": ("current_ratio",), "quick_ratio": ("quick_ratio",),
    "bps": ("bps",), "eps": ("eps",), "dt_eps": ("dt_eps",),
    "assets_turn": ("assets_turn",), "inv_turn": ("inv_turn",),
    "ar_turn": ("ar_turn",),
    "ocf_to_profit": ("ocf_to_profit",),
    "ocf_to_or": ("ocf_to_or",),
    "dtprofit_to_profit": ("dtprofit_to_profit",),
    "ebit_to_interest": ("ebit_to_interest",),
    "ocf_to_debt": ("ocf_to_debt",),
}


class SelectionEngine:
    """选股引擎 — 从候选池中筛选标的"""

    def __init__(self) -> None:
        self._evaluator = ExpressionEvaluator()
        self._fusion_engine = FusionEngine()
        self.last_diagnostics: dict[str, Any] = {}

    async def run(
        self,
        strategy_id: str,
        signal_date: date,
        universe: UniverseProvider,
    ) -> dict[str, dict[str, Any]]:
        """执行选股

        Args:
            strategy_id: 策略编码（对应 td_strategy.strategy_id）
            signal_date: 信号日期
            universe: 候选标的提供者

        Returns:
            {symbol: {"score": float, "direction": str}} 入选标的及其得分
        """
        # 1. 加载策略配置
        strategy = await Strategy.get_or_none(strategy_id=strategy_id)
        if not strategy:
            raise ValueError(f"策略不存在: {strategy_id}")

        config = strategy.config or {}
        groups = config.get("groups", [])
        top_n = config.get("top_n")
        exclude_short = config.get("exclude_short", True)

        if not groups:
            logger.warning(f"策略无规则组配置: {strategy_id}")
            self.last_diagnostics = {"filter_steps": [], "factor_values": {}}
            return {}

        # 2. 获取候选标的
        symbols = await universe.get_symbols()
        if not symbols:
            logger.info(f"选股 | 候选池为空: {universe.describe()}")
            self.last_diagnostics = {"filter_steps": [], "factor_values": {}}
            return {}

        logger.info(
            f"选股 | strategy={strategy_id} date={signal_date} "
            f"pool={universe.describe()} symbols={len(symbols)}",
        )

        # 3. 收集依赖因子
        rule_ids = self._collect_rule_ids(groups)
        factor_ids = await self._collect_factor_ids(rule_ids)

        # 4. 加载截面因子数据
        cross_section_df = await self._load_cross_section_data(symbols, factor_ids, signal_date)
        if cross_section_df is None or cross_section_df.empty:
            logger.warning(f"截面因子数据为空: date={signal_date}")
            self.last_diagnostics = {"filter_steps": [], "factor_values": {}}
            return {}

        # 5. 逐规则组执行截面评估 + 组内融合
        filter_steps: list[dict[str, Any]] = [{
            "step_type": "universe",
            "label": universe.describe(),
            "count": len(symbols),
            "pass_rate": 1.0,
        }]
        group_results: list[pd.Series] = []  # 每组一个 score Series
        for group in groups:
            group_rules = group.get("rules", [])
            if not group_rules:
                continue

            fusion_cfg = FusionConfig(**group.get("fusion", {}))

            rule_scores: dict[str, pd.Series] = {}
            for rule_item in group_rules:
                rid = rule_item["rule_id"]

                rule_model = await RuleRegistryModel.get_or_none(rule_id=rid)
                if not rule_model:
                    logger.warning(f"规则未找到: {rid}")
                    continue

                definition = rule_model.definition or {}
                factors = rule_model.factors or []
                rule_type = rule_model.rule_type

                if rule_type == "expression":
                    # 截面表达式：使用 bullish_expr / bearish_expr 或 score_expr
                    score_expr = definition.get("score_expr", "")
                    bullish_expr = definition.get("bullish_expr", "")
                    bearish_expr = definition.get("bearish_expr", "")

                    if score_expr:
                        scores = self._evaluate_cross_section_expr(score_expr, cross_section_df, factors)
                    elif bullish_expr:
                        bullish_mask = self._evaluate_cross_section_expr(bullish_expr, cross_section_df, factors)
                        if bearish_expr:
                            bearish_mask = self._evaluate_cross_section_expr(
                                bearish_expr, cross_section_df, factors,
                            )
                        else:
                            bearish_mask = pd.Series(False, index=cross_section_df.index)
                        scores = bullish_mask.astype(float) * 1.0 - bearish_mask.astype(float) * 1.0
                    else:
                        continue
                    rule_scores[rid] = scores
                    filter_steps.append(self._build_rule_filter_step(
                        rule_model=rule_model,
                        scores=scores,
                        total_count=len(cross_section_df),
                        weight=rule_item.get("weight"),
                        expression=score_expr or bullish_expr,
                    ))
                else:
                    continue

            if not rule_scores:
                continue

            # 组内融合（截面模式：score 作为权重，方向由正负决定）
            group_result = self._fuse_cross_section_group(rule_scores, fusion_cfg)
            group_results.append(group_result)
            group_count = int((group_result != 0).sum())
            filter_steps.append({
                "step_type": "group",
                "label": group.get("name") or group.get("group_id") or "规则组",
                "count": group_count,
                "pass_rate": group_count / len(group_result) if len(group_result) else 0.0,
                "group_method": fusion_cfg.method,
            })

        if not group_results:
            self.last_diagnostics = {"filter_steps": filter_steps, "factor_values": {}}
            return {}

        # 6. 组间融合（取均值）
        final_scores = pd.concat(group_results, axis=1).mean(axis=1, skipna=False)
        final_scores = final_scores.sort_values(ascending=False)

        # Top N
        if top_n and top_n < len(final_scores):
            final_scores = final_scores.head(top_n)

        final_count = int((final_scores != 0).sum())
        filter_steps.append({
            "step_type": "final",
            "label": "最终入选",
            "count": final_count,
            "pass_rate": final_count / len(symbols) if symbols else 0.0,
        })
        self.last_diagnostics = {
            "filter_steps": filter_steps,
            "factor_values": self._extract_factor_values(cross_section_df),
        }

        # 7. 构建选股结果
        results: dict[str, dict[str, Any]] = {}
        for symbol_idx, score in final_scores.items():
            if pd.isna(score) or score == 0:
                continue
            symbol = str(symbol_idx)
            direction = RuleDirection.BULLISH if score > 0 else RuleDirection.BEARISH
            if direction == RuleDirection.BEARISH and exclude_short:
                continue
            results[symbol] = {
                "score": round(float(score), 4),
                "direction": direction,
                "confidence": round(abs(float(score)), 4),
            }

        # 8. 落库
        await self._persist_results(strategy, universe.instance_id, signal_date, results)

        logger.info(f"选股 | strategy={strategy_id} selected={len(results)}/{len(symbols)}")
        return results

    @staticmethod
    def _build_rule_filter_step(
        rule_model: RuleRegistryModel,
        scores: pd.Series,
        total_count: int,
        weight: float | None,
        expression: str,
    ) -> dict[str, Any]:
        hit_count = int((scores != 0).sum())
        return {
            "step_type": "rule",
            "label": rule_model.name or rule_model.rule_id,
            "count": hit_count,
            "pass_rate": hit_count / total_count if total_count else 0.0,
            "rule_id": rule_model.rule_id,
            "expression": expression,
            "factors": rule_model.factors or [],
            "weight": weight,
        }

    @staticmethod
    def _extract_factor_values(
        cross_section_df: pd.DataFrame,
    ) -> dict[str, dict[str, float | None]]:
        values: dict[str, dict[str, float | None]] = {}
        for symbol_idx, row in cross_section_df.iterrows():
            symbol_values: dict[str, float | None] = {}
            for key, value in row.items():
                symbol_values[str(key)] = None if pd.isna(value) else float(value)
            values[str(symbol_idx)] = symbol_values
        return values

    def _fuse_cross_section_group(
        self,
        rule_scores: dict[str, pd.Series],
        fusion_cfg: FusionConfig,
    ) -> pd.Series:
        """截面模式下融合规则组（用 FusionEngine 逐个标的融合）"""
        if not rule_scores:
            return pd.Series(dtype=float)

        first_series = next(iter(rule_scores.values()))
        symbols = first_series.index
        result_scores = pd.Series(0.0, index=symbols)

        for symbol in symbols:
            per_symbol_results: list[RuleResult] = []
            for rule_id, series in rule_scores.items():
                val = series.get(symbol, 0.0)
                if pd.isna(val):
                    val = 0.0
                passed = val != 0
                if val > 0:
                    direction = RuleDirection.BULLISH
                elif val < 0:
                    direction = RuleDirection.BEARISH
                else:
                    direction = RuleDirection.NEUTRAL
                per_symbol_results.append(RuleResult(
                    rule_id=rule_id,
                    passed=passed,
                    score=abs(float(val)),
                    direction=direction,
                    confidence=abs(float(val)),
                ))
            fused = self._fusion_engine.fuse(per_symbol_results, fusion_cfg)
            if fused.passed:
                result_scores[symbol] = fused.score * (1.0 if fused.direction == RuleDirection.BULLISH else -1.0)

        return result_scores

    def _evaluate_cross_section_expr(
        self,
        expr: str,
        cross_section_df: pd.DataFrame,
        factor_ids: list[str],
    ) -> pd.Series:
        """求值截面表达式，返回 bool Series"""
        try:
            ast = parse_expression(expr)
            # 为 DataFrame 中每行构建 dict → 求值
            results = cross_section_df.apply(
                lambda row: self._evaluator.evaluate(
                    ast=ast,
                    factor_values={
                        fid: float(row[fid])
                        for fid in factor_ids
                        if fid in row.index and pd.notna(row[fid])
                    },
                ),
                axis=1,
            )
            if isinstance(results, pd.Series) and results.dtype == bool:
                return results
            if isinstance(results, pd.Series):
                return results.astype(bool)
            return pd.Series(False, index=cross_section_df.index)
        except Exception as e:
            logger.warning(f"截面表达式求值异常: expr='{expr}' error={e}")
            return pd.Series(False, index=cross_section_df.index)

    @staticmethod
    def _collect_rule_ids(groups: list[dict]) -> list[str]:
        """从配置中收集所有规则 ID"""
        ids: set[str] = set()
        for group in groups:
            for rule in group.get("rules", []):
                if isinstance(rule, dict) and rule.get("rule_id"):
                    ids.add(rule["rule_id"])
        return list(ids)

    @staticmethod
    async def _collect_factor_ids(rule_ids: list[str]) -> list[str]:
        """收集所有规则依赖的因子 ID"""
        if not rule_ids:
            return []
        rule_models = await RuleRegistryModel.filter(rule_id__in=rule_ids)
        factor_ids: set[str] = set()
        for m in rule_models:
            if m.factors:
                factor_ids.update(m.factors)
        return list(factor_ids)

    async def _load_cross_section_data(
        self,
        symbols: list[str],
        factor_ids: list[str],
        signal_date: date,
    ) -> pd.DataFrame | None:
        """加载截面因子数据（与旧版 SelectionEngine 相同的三个数据源）"""
        if not factor_ids:
            return None

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
        if fv_factor_ids:
            df = await self._load_factor_value_data(symbols, fv_factor_ids, signal_date)
            if df is not None:
                dfs.append(df)
        if di_factor_ids:
            df = await self._load_daily_indicator_data(symbols, di_factor_ids, signal_date)
            if df is not None:
                dfs.append(df)
        if fi_factor_ids:
            df = await self._load_financial_indicator_data(symbols, fi_factor_ids, signal_date)
            if df is not None:
                dfs.append(df)

        if not dfs:
            return None
        result = dfs[0]
        for df in dfs[1:]:
            result = result.join(df, how="outer")
        result = result[result.index.isin(symbols)]
        return result if not result.empty else None

    @staticmethod
    async def _load_factor_value_data(
        symbols: list[str], factor_ids: list[str], signal_date: date,
    ) -> pd.DataFrame | None:
        from xqtrader.domain.factor.models.factor_value import FacFactorValue

        records = await FacFactorValue.filter(
            trade_date=signal_date,
            pool_id=_DEFAULT_POOL_ID,
            factor_id__in=factor_ids,
            symbol__in=symbols,
        )
        if not records:
            return None
        rows = [{"symbol": r.symbol, r.factor_id: r.factor_value} for r in records if r.factor_value is not None]
        if not rows:
            return None
        df = pd.DataFrame(rows)
        df = df.groupby("symbol").agg("first").reset_index()
        return df.set_index("symbol")

    @staticmethod
    async def _load_daily_indicator_data(
        symbols: list[str], factor_ids: list[str], signal_date: date,
    ) -> pd.DataFrame | None:
        from xqtrader.domain.market.models.daily_indicator import DailyIndicator

        records = await DailyIndicator.filter(trade_date=signal_date, symbol__in=symbols)
        if not records:
            return None
        rows: list[dict[str, Any]] = []
        for r in records:
            row: dict[str, Any] = {"symbol": r.symbol}
            for fid in factor_ids:
                field = _DAILY_INDICATOR_FIELD_MAP.get(fid)
                if field:
                    val = getattr(r, field, None)
                    if val is not None:
                        row[fid] = float(val)
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

    @staticmethod
    async def _load_financial_indicator_data(
        symbols: list[str], factor_ids: list[str], signal_date: date,
    ) -> pd.DataFrame | None:
        from sqlalchemy import and_, func, select

        from xqtrader.domain.market.models.financial_indicator import FinancialIndicator

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

    @transactional(bind_key="trading")
    async def _persist_results(
        self,
        strategy: Strategy,
        instance_id: int,
        signal_date: date,
        results: dict[str, dict[str, Any]],
    ) -> None:
        """选股结果落库 — 幂等"""
        await SelectionResult.delete_many(
            instance_id=instance_id,
            strategy_id=strategy.strategy_id,
            signal_date=signal_date,
        )
        if not results:
            return

        instances = [
            SelectionResult(
                instance_id=instance_id,
                strategy_id=strategy.strategy_id,
                signal_date=signal_date,
                symbol=symbol,
                score=data["score"],
                rank=rank + 1,
            )
            for rank, (symbol, data) in enumerate(
                sorted(results.items(), key=lambda x: x[1]["score"], reverse=True),
            )
        ]
        await SelectionResult.bulk_create_or_update(
            instances,
            on_conflict=["instance_id", "strategy_id", "signal_date", "symbol"],
            update_fields=["score", "rank"],
        )
