"""成熟截面选股策略 — 跨样本池验证（引擎直调 + 数据合理性）。"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from xqtrader.domain.trading.models.strategy import Strategy
from xqtrader.domain.trading.rules.base import FullMarketUniverse, IndexUniverse
from xqtrader.domain.trading.selection.engine import SelectionEngine

SIGNAL_DATE = date(2026, 6, 29)

# 业界主流成熟策略（不含 test_* 占位）
MAINSTREAM_STRATEGIES: dict[str, list[str]] = {
    "buffett_value": ["cs_value_filter", "cs_quality_filter", "cs_low_volatility"],
    "graham_deep_value": ["cs_deep_value", "cs_financial_safety", "cs_low_leverage"],
    "high_dividend": ["cs_high_dividend", "cs_value_filter", "cs_financial_safety"],
    "low_vol_leader": ["cs_low_volatility", "cs_quality_filter", "cs_rsi_range"],
    "multi_factor_resonance": ["cs_multi_factor_resonance"],  # 含 barra_momentum 等 7 因子
    "peter_lynch_growth": [
        "cs_high_growth_roe", "cs_value_filter", "cs_strong_momentum", "cs_quality_filter",
    ],
    "trend_fund_resonance": ["cs_strong_momentum", "cs_fund_flow_filter", "cs_rsi_range"],
    "value_momentum": [
        "cs_value_filter", "cs_low_volatility", "cs_momentum_filter", "cs_fund_flow_filter",
    ],
}

UNIVERSE_CASES: list[tuple[str, str | None]] = [
    ("index", "idx_300"),
    ("index", "idx_1000"),
    ("full_market", None),
]


def _build_universe(universe_type: str, universe_param: str | None):
    if universe_type == "index":
        return IndexUniverse(universe_param or "idx_300")
    if universe_type == "full_market":
        return FullMarketUniverse()
    raise ValueError(f"unsupported universe: {universe_type}")


def _validate_factor_sanity(symbol: str, factor_values: dict[str, Any]) -> None:
    """入选标的因子值基本合理性检查。"""
    pe = factor_values.get("pe_ttm")
    if pe is not None:
        assert pe > 0, f"{symbol} pe_ttm 应 > 0, 实际 {pe}"
        assert pe < 2000, f"{symbol} pe_ttm 异常偏高: {pe}"

    roe = factor_values.get("roe")
    if roe is not None:
        assert -500 <= roe <= 500, f"{symbol} roe 超出合理范围: {roe}"

    mom = factor_values.get("mom_20d")
    if mom is not None:
        assert -1.0 <= mom <= 5.0, f"{symbol} mom_20d 异常: {mom}"

    rsi = factor_values.get("rsi_14")
    if rsi is not None:
        assert 0 <= rsi <= 100, f"{symbol} rsi_14 超出 [0,100]: {rsi}"

    vol = factor_values.get("hist_vol_20")
    if vol is not None:
        assert 0 <= vol <= 3.0, f"{symbol} hist_vol_20 异常: {vol}"

    dv = factor_values.get("dv_ratio")
    if dv is not None:
        assert 0 <= dv <= 30, f"{symbol} dv_ratio 异常: {dv}"


def _validate_trend_fund_item(factor_values: dict[str, Any]) -> None:
    mom = factor_values.get("mom_20d")
    ff = factor_values.get("cs_main_net_pct")
    rsi = factor_values.get("rsi_14")
    assert mom is not None and mom > 0.05, f"趋势资金共振 mom_20d 应 > 0.05, 实际 {mom}"
    assert ff is not None and ff > 0, f"趋势资金共振 cs_main_net_pct 应 > 0, 实际 {ff}"
    assert rsi is not None and 30 < rsi < 70, f"趋势资金共振 rsi_14 应在 (30,70), 实际 {rsi}"


class TestMainstreamStrategyConfigs:
    """策略配置完整性 — 无空 groups。"""

    @pytest.mark.asyncio(loop_scope="session")
    @pytest.mark.parametrize("strategy_id", list(MAINSTREAM_STRATEGIES))
    async def test_strategy_has_rule_groups(self, app_with_datasource, strategy_id: str) -> None:
        del app_with_datasource
        strategy = await Strategy.get_or_none(strategy_id=strategy_id)
        assert strategy is not None, f"策略不存在: {strategy_id}"
        groups = (strategy.config or {}).get("groups", [])
        assert groups, f"策略 {strategy_id} config.groups 为空"
        rule_ids = {
            r["rule_id"]
            for g in groups
            for r in g.get("rules", [])
            if isinstance(r, dict) and r.get("rule_id")
        }
        expected = set(MAINSTREAM_STRATEGIES[strategy_id])
        assert expected <= rule_ids, f"{strategy_id} 缺少规则: {expected - rule_ids}"


class TestMainstreamStrategySelection:
    """跨样本池选股执行与结果合理性。"""

    @pytest.mark.asyncio(loop_scope="session")
    @pytest.mark.parametrize("strategy_id", list(MAINSTREAM_STRATEGIES))
    @pytest.mark.parametrize("universe_type,universe_param", UNIVERSE_CASES)
    async def test_run_selection_pipeline(
        self,
        app_with_datasource,
        strategy_id: str,
        universe_type: str,
        universe_param: str | None,
    ) -> None:
        del app_with_datasource
        engine = SelectionEngine()
        universe = _build_universe(universe_type, universe_param)
        symbols = await universe.get_symbols()
        assert symbols, f"样本池为空: {universe_type}/{universe_param}"

        results = await engine.run(strategy_id, SIGNAL_DATE, universe)
        steps = engine.last_diagnostics.get("filter_steps", [])
        assert steps, f"{strategy_id} filter_steps 为空"
        assert steps[0]["step_type"] == "universe"
        assert steps[0]["count"] == len(symbols)

        step_rule_ids = {
            s["rule_id"] for s in steps if s.get("step_type") == "rule" and s.get("rule_id")
        }
        for rid in MAINSTREAM_STRATEGIES[strategy_id]:
            assert rid in step_rule_ids, f"{strategy_id} 未执行规则 {rid}"

        factor_snap = engine.last_diagnostics.get("factor_values", {})
        for symbol, data in results.items():
            assert data["score"] > 0, f"{symbol} 得分应 > 0"
            assert data["direction"] in ("bullish", "bearish", "long", "short")
            fv = factor_snap.get(symbol, {})
            _validate_factor_sanity(symbol, fv)
            if strategy_id == "trend_fund_resonance":
                _validate_trend_fund_item(fv)

        rule_hits = [s for s in steps if s.get("step_type") == "rule"]
        assert any(s.get("count", 0) > 0 for s in rule_hits), (
            f"{strategy_id}@{universe_type}/{universe_param} 所有规则命中为 0，因子数据可能缺失"
        )


class TestMainstreamStrategySmokeSummary:
    """沪深300 冒烟：每策略至少能产出结果或明确筛空。"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_idx300_smoke_all_strategies(self, app_with_datasource) -> None:
        del app_with_datasource
        engine = SelectionEngine()
        universe = IndexUniverse("idx_300")
        summary: list[str] = []

        for strategy_id in MAINSTREAM_STRATEGIES:
            results = await engine.run(strategy_id, SIGNAL_DATE, universe)
            steps = engine.last_diagnostics.get("filter_steps", [])
            final = next((s for s in steps if s.get("step_type") == "final"), {})
            summary.append(
                f"{strategy_id}: selected={len(results)} final_count={final.get('count', 0)}",
            )

        with_results = [line for line in summary if "selected=0 " not in line]
        assert len(with_results) >= 4, "过半策略无选股结果:\n" + "\n".join(summary)
