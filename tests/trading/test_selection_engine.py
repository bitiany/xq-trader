"""选股引擎单元测试 — SelectionEngine + RuleRegistry + UniverseProvider + SPI 插件"""

from datetime import date

import pandas as pd
import pytest

from xqtrader.domain.factor.services.cross_section_reader import is_risk_warning_name
from xqtrader.domain.trading.rules.base import (
    CustomUniverse,
    RuleContext,
    RuleResult,
    SelectionScore,
)
from xqtrader.domain.trading.rules.plugins.multi_factor_resonance import (
    MultiFactorResonancePlugin,
)
from xqtrader.domain.trading.rules.registry import ExpressionRule, RuleRegistry
from xqtrader.domain.trading.selection.engine import SelectionEngine


class TestRiskWarningFilter:
    """风险警示股(ST/*ST/PT)过滤测试"""

    def test_st_name_detected(self):
        assert is_risk_warning_name("ST三木") is True

    def test_star_st_name_detected(self):
        assert is_risk_warning_name("*ST海航") is True

    def test_pt_name_detected(self):
        assert is_risk_warning_name("PT水仙") is True

    def test_normal_name_not_detected(self):
        assert is_risk_warning_name("贵州茅台") is False
        assert is_risk_warning_name("中国平安") is False
        assert is_risk_warning_name("宁德时代") is False

    def test_empty_name_not_detected(self):
        assert is_risk_warning_name("") is False


class TestCustomUniverse:
    """CustomUniverse 测试"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_get_symbols(self):
        universe = CustomUniverse(["600519.SH", "000858.SZ", "601318.SH"])
        symbols = await universe.get_symbols()
        assert symbols == ["600519.SH", "000858.SZ", "601318.SH"]

    @pytest.mark.asyncio(loop_scope="session")
    async def test_describe(self):
        universe = CustomUniverse(["600519.SH"])
        assert "CustomUniverse" in universe.describe()
        assert "n=1" in universe.describe()


class TestRuleRegistry:
    """RuleRegistry 测试"""

    def test_register_expression(self):
        registry = RuleRegistry()
        registry.register_expression(
            rule_id="test_rule",
            name="测试规则",
            category="cross_section",
            expression="roe > 12",
        )
        assert registry.has("test_rule")

    def test_register_plugin(self):
        registry = RuleRegistry()
        plugin = MultiFactorResonancePlugin()
        registry.register_plugin(plugin)
        assert registry.has("cs_multi_factor_resonance")

    def test_get_expression_rule(self):
        registry = RuleRegistry()
        registry.register_expression(
            rule_id="test_rule",
            name="测试规则",
            category="cross_section",
            expression="roe > 12",
        )
        rule = registry.get("test_rule")
        assert isinstance(rule, ExpressionRule)
        assert rule.expression == "roe > 12"

    def test_get_plugin(self):
        registry = RuleRegistry()
        plugin = MultiFactorResonancePlugin()
        registry.register_plugin(plugin)
        rule = registry.get("cs_multi_factor_resonance")
        assert isinstance(rule, MultiFactorResonancePlugin)

    def test_get_nonexistent_raises(self):
        registry = RuleRegistry()
        with pytest.raises(KeyError, match="规则不存在"):
            registry.get("nonexistent")

    def test_list_rules(self):
        registry = RuleRegistry()
        registry.register_expression(
            rule_id="expr_rule", name="表达式规则",
            category="cross_section", expression="roe > 12",
        )
        plugin = MultiFactorResonancePlugin()
        registry.register_plugin(plugin)
        rules = registry.list_rules()
        assert len(rules) == 2
        types = {r["type"] for r in rules}
        assert "expression" in types
        assert "spi" in types


class TestExpressionRuleEvaluate:
    """ExpressionRule.evaluate 测试"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_evaluate_true(self):
        registry = RuleRegistry()
        registry.register_expression(
            rule_id="roe_filter", name="ROE过滤",
            category="cross_section", expression="roe > 12",
        )
        rule = registry.get("roe_filter")
        ctx = RuleContext(
            symbol="600519.SH",
            signal_date=date.today(),
            factor_values={"roe": 15.0},
        )
        result = await rule.evaluate(ctx)
        assert result.passed is True
        assert result.rule_id == "roe_filter"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_evaluate_false(self):
        registry = RuleRegistry()
        registry.register_expression(
            rule_id="roe_filter", name="ROE过滤",
            category="cross_section", expression="roe > 12",
        )
        rule = registry.get("roe_filter")
        ctx = RuleContext(
            symbol="600519.SH",
            signal_date=date.today(),
            factor_values={"roe": 10.0},
        )
        result = await rule.evaluate(ctx)
        assert result.passed is False

    @pytest.mark.asyncio(loop_scope="session")
    async def test_evaluate_and_expression(self):
        registry = RuleRegistry()
        registry.register_expression(
            rule_id="value_quality", name="价值质量",
            category="cross_section",
            expression="roe > 12 and pe_ttm < 25",
        )
        rule = registry.get("value_quality")
        ctx = RuleContext(
            symbol="600519.SH",
            signal_date=date.today(),
            factor_values={"roe": 15.0, "pe_ttm": 20.0},
        )
        result = await rule.evaluate(ctx)
        assert result.passed is True

    @pytest.mark.asyncio(loop_scope="session")
    async def test_evaluate_missing_factor_returns_failed(self):
        registry = RuleRegistry()
        registry.register_expression(
            rule_id="missing_factor", name="缺失因子",
            category="cross_section", expression="unknown_factor > 0",
        )
        rule = registry.get("missing_factor")
        ctx = RuleContext(
            symbol="600519.SH",
            signal_date=date.today(),
            factor_values={"roe": 15.0},
        )
        result = await rule.evaluate(ctx)
        assert result.passed is False
        assert "error" in result.detail


class TestMultiFactorResonancePlugin:
    """多因子共振 SPI 插件测试"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_evaluate_single_all_dims_pass(self):
        plugin = MultiFactorResonancePlugin()
        ctx = RuleContext(
            symbol="600519.SH",
            signal_date=date.today(),
            factor_values={
                "mom_20d": 0.05,
                "hist_vol_20": 0.25,
                "ep": 0.05,
                "cs_main_net_pct": 0.02,
                "rsi_14": 55.0,
                "boll_position": 0.5,
            },
        )
        result = await plugin.evaluate(ctx)
        assert result.passed is True
        assert result.direction == "long"
        assert result.confidence > 0

    @pytest.mark.asyncio(loop_scope="session")
    async def test_evaluate_single_few_dims(self):
        plugin = MultiFactorResonancePlugin()
        ctx = RuleContext(
            symbol="000001.SZ",
            signal_date=date.today(),
            factor_values={
                "mom_20d": -0.05,  # 动量维度失败
                "hist_vol_20": 0.5,  # 低波维度失败
                "ep": 0.02,  # 价值维度失败
                "cs_main_net_pct": -0.01,  # 资金流维度失败
                "rsi_14": 80.0,  # 技术面维度失败
                "boll_position": 0.95,  # 技术面维度失败
            },
        )
        result = await plugin.evaluate(ctx)
        assert result.passed is False

    @pytest.mark.asyncio(loop_scope="session")
    async def test_evaluate_cross_section(self):
        plugin = MultiFactorResonancePlugin()
        df = pd.DataFrame(
            {
                "mom_20d": [0.05, -0.03, 0.08],
                "hist_vol_20": [0.25, 0.5, 0.2],
                "ep": [0.05, 0.02, 0.06],
                "cs_main_net_pct": [0.02, -0.01, 0.03],
                "rsi_14": [55.0, 80.0, 45.0],
                "boll_position": [0.5, 0.95, 0.3],
            },
            index=["600519.SH", "000001.SZ", "601318.SH"],
        )
        ctx = RuleContext(
            symbol="600519.SH",
            signal_date=date.today(),
            cross_section_df=df,
        )
        result = await plugin.evaluate(ctx)
        assert result.rule_id == "cs_multi_factor_resonance"
        # 600519.SH 各维度都较好，应通过
        assert result.passed is True


class TestSelectionEngineCrossSection:
    """SelectionEngine 截面选股测试（纯内存，不依赖数据库）"""

    def test_evaluate_expression_cross_section(self):
        """测试截面表达式求值"""
        engine = SelectionEngine()
        rule = ExpressionRule(
            rule_id="test_roe",
            name="ROE测试",
            category="cross_section",
            expression="roe > 12",
        )
        df = pd.DataFrame(
            {"roe": [10.0, 15.0, 20.0, 8.0]},
            index=["A", "B", "C", "D"],
        )
        result = engine._evaluate_expression_cross_section(rule, df, {})
        assert isinstance(result, pd.Series)
        assert result.loc["A"] == 0.0  # 10 < 12
        assert result.loc["B"] == 1.0  # 15 > 12
        assert result.loc["C"] == 1.0  # 20 > 12
        assert result.loc["D"] == 0.0  # 8 < 12

    def test_evaluate_rank_expression(self):
        """测试截面 rank 表达式"""
        engine = SelectionEngine()
        rule = ExpressionRule(
            rule_id="test_rank",
            name="Rank测试",
            category="cross_section",
            expression="rank(roe) > 0.5",
        )
        df = pd.DataFrame(
            {"roe": [10.0, 15.0, 20.0, 5.0]},
            index=["A", "B", "C", "D"],
        )
        result = engine._evaluate_expression_cross_section(rule, df, {})
        assert isinstance(result, pd.Series)
        assert result.loc["C"] == 1.0  # rank=1.0 > 0.5
        assert result.loc["D"] == 0.0  # rank=0.25 < 0.5

    def test_combine_cross_section(self):
        """测试截面规则组合"""
        from xqtrader.domain.trading.rules.combination.weighted_score import (
            WeightedScoreCombination,
        )

        engine = SelectionEngine()
        rule_results = {
            "r1": pd.Series([0.8, 0.6, 0.2], index=["A", "B", "C"]),
            "r2": pd.Series([0.4, 0.9, 0.1], index=["A", "B", "C"]),
        }
        combination = WeightedScoreCombination()
        weights = {"r1": 0.6, "r2": 0.4}
        combined = engine._combine_cross_section(
            rule_results, combination, weights, {"threshold": 0.5},
        )
        assert isinstance(combined, pd.Series)
        # A: (0.6*0.8 + 0.4*0.4)/1.0 = 0.64
        assert abs(combined.loc["A"] - 0.64) < 0.01
        # B: (0.6*0.6 + 0.4*0.9)/1.0 = 0.72
        assert abs(combined.loc["B"] - 0.72) < 0.01
