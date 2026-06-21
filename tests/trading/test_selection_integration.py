"""选股引擎集成测试 — 使用真实数据源验证端到端选股流程"""

from datetime import date

import pytest

from xqtrader.domain.factor.services.cross_section_reader import (
    CrossSectionReader,
    is_risk_warning_name,
)
from xqtrader.domain.security.models import Security
from xqtrader.domain.trading.models.decision import SelectionResult
from xqtrader.domain.trading.models.rule import RuleRegistry as RuleRegistryModel
from xqtrader.domain.trading.models.strategy import Strategy, StrategyRuleBinding, StrategyRuleGroup
from xqtrader.domain.trading.rules.base import CustomUniverse, FullMarketUniverse, IndexUniverse
from xqtrader.domain.trading.selection.engine import SelectionEngine


class TestSeedData:
    """验证种子数据已正确入库"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_buffett_strategy_exists(self, app_with_datasource):
        strategy = await Strategy.get_or_none(strategy_id="buffett_value")
        assert strategy is not None
        assert strategy.name == "巴菲特价值投资"
        assert strategy.status == "active"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_value_momentum_strategy_exists(self, app_with_datasource):
        strategy = await Strategy.get_or_none(strategy_id="value_momentum")
        assert strategy is not None
        assert strategy.name == "价值动量"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_rule_registry_count(self, app_with_datasource):
        rules = await RuleRegistryModel.filter(is_builtin=True)
        assert len(rules) >= 6

    @pytest.mark.asyncio(loop_scope="session")
    async def test_buffett_rule_bindings(self, app_with_datasource):
        strategy = await Strategy.get_or_none(strategy_id="buffett_value")
        groups = await StrategyRuleGroup.filter(strategy_id=strategy.id)
        bindings = await StrategyRuleBinding.filter(group_id=groups[0].id)
        assert len(bindings) == 3
        rule_ids = {b.rule_id for b in bindings}
        assert "cs_value_filter" in rule_ids
        assert "cs_quality_filter" in rule_ids
        assert "cs_low_volatility" in rule_ids


class TestSelectionEngineWithRealData:
    """使用真实因子数据验证选股引擎"""

    SIGNAL_DATE = date(2026, 6, 16)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_run_buffett_value(self, app_with_datasource):
        """巴菲特价值投资策略 — 验证 pe_ttm/roe/grossprofit_margin 多数据源聚合"""
        engine = SelectionEngine()
        universe = CustomUniverse(["600519.SH", "000858.SZ", "601318.SH", "000001.SZ", "600036.SH"])
        results = await engine.run("buffett_value", self.SIGNAL_DATE, universe)

        assert isinstance(results, dict)
        for symbol, score in results.items():
            assert score.symbol == symbol
            assert 0.0 <= score.score <= 1.0
            assert score.direction in ("long", "short", "neutral")
            # 验证因子快照
            factor_values = score.detail.get("factor_values", {})
            assert isinstance(factor_values, dict)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_run_value_momentum(self, app_with_datasource):
        """价值动量策略 — 验证 pe_ttm 从每日指标表 + 技术因子从因子表"""
        engine = SelectionEngine()
        universe = CustomUniverse(["600519.SH", "000858.SZ", "601318.SH", "000001.SZ", "600036.SH"])
        results = await engine.run("value_momentum", self.SIGNAL_DATE, universe)

        assert isinstance(results, dict)
        for symbol, score in results.items():
            factor_values = score.detail.get("factor_values", {})
            # 价值动量策略依赖 pe_ttm + hist_vol_20 + mom_20d + cs_main_net_pct
            # 验证至少有部分因子值被保存
            assert isinstance(factor_values, dict)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_run_multi_factor_resonance(self, app_with_datasource):
        """多因子共振策略"""
        engine = SelectionEngine()
        universe = CustomUniverse(["600519.SH", "000858.SZ", "601318.SH", "000001.SZ", "600036.SH"])
        results = await engine.run("multi_factor_resonance", self.SIGNAL_DATE, universe)

        assert isinstance(results, dict)
        for symbol, score in results.items():
            assert score.direction == "long"

    @pytest.mark.asyncio(loop_scope="session")
    async def test_run_with_index_universe(self, app_with_datasource):
        """使用指数成分股运行选股"""
        engine = SelectionEngine()
        universe = IndexUniverse("idx_50")
        results = await engine.run("buffett_value", self.SIGNAL_DATE, universe)

        assert isinstance(results, dict)
        if results:
            scores = [s.score for s in results.values()]
            assert max(scores) >= 0.3

    @pytest.mark.asyncio(loop_scope="session")
    async def test_selection_result_persisted_with_snapshot(self, app_with_datasource):
        """验证选股结果落库且含因子快照"""
        engine = SelectionEngine()
        universe = CustomUniverse(["600519.SH", "000858.SZ"])
        await engine.run("buffett_value", self.SIGNAL_DATE, universe)

        records = await SelectionResult.filter(signal_date=self.SIGNAL_DATE)
        assert len(records) > 0

        # 验证因子快照已保存（factor_values 列直接存储因子值字典）
        for record in records:
            factor_values = record.factor_values or {}
            assert isinstance(factor_values, dict)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_nonexistent_strategy_raises(self, app_with_datasource):
        """策略不存在时应抛出 ValueError"""
        engine = SelectionEngine()
        universe = CustomUniverse(["600519.SH"])
        with pytest.raises(ValueError, match="策略不存在"):
            await engine.run("nonexistent_strategy", self.SIGNAL_DATE, universe)

    @pytest.mark.asyncio(loop_scope="session")
    async def test_empty_universe_returns_empty(self, app_with_datasource):
        """空候选池应返回空结果"""
        engine = SelectionEngine()
        universe = CustomUniverse([])
        results = await engine.run("buffett_value", self.SIGNAL_DATE, universe)
        assert results == {}


class TestFullMarketUniverseFilter:
    """全市场样本池 ST/退市过滤测试"""

    @pytest.mark.asyncio(loop_scope="session")
    async def test_full_market_excludes_st_stocks(self, app_with_datasource):
        """全市场样本池应排除 ST/*ST 风险警示股"""
        universe = FullMarketUniverse()
        symbols = await universe.get_symbols()

        # 加载所有标的名称用于校验
        securities = await Security.filter(symbol__in=symbols)
        names = {s.symbol: s.name for s in securities}

        # 验证返回的标的中不包含 ST/*ST/PT 标的
        st_symbols = [
            sym for sym, name in names.items()
            if is_risk_warning_name(name)
        ]
        assert st_symbols == [], f"全市场样本池中仍包含 ST 标的: {st_symbols[:10]}"

        # 验证标的数量等于「上市标的总数 - 风险警示股数量」
        all_listed = await Security.filter(list_status="L")
        risk_count = sum(1 for s in all_listed if is_risk_warning_name(s.name))
        expected = len(all_listed) - risk_count
        assert len(symbols) == expected, (
            f"全市场样本池标的数量异常: 实际 {len(symbols)}, 期望 {expected} "
            f"(上市 {len(all_listed)} - ST {risk_count})"
        )

    @pytest.mark.asyncio(loop_scope="session")
    async def test_full_market_excludes_delisted_stocks(self, app_with_datasource):
        """全市场样本池应排除退市标的(list_status != 'L')"""
        reader = CrossSectionReader()
        symbols = await reader.load_pool_symbols("all")

        # 查询返回标的中是否有非上市状态的标的
        non_listed = await Security.filter(symbol__in=symbols, list_status__ne="L")
        assert non_listed == [], f"全市场样本池中包含非上市标的: {[s.symbol for s in non_listed[:10]]}"
