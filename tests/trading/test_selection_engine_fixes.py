"""SelectionEngine 截面表达式 / SPI 插件修复回归测试。"""

from datetime import date

import pandas as pd

from xqtrader.domain.trading.selection.engine import SelectionEngine


class TestSelectionEngineCrossSectionFixes:
    def test_evaluate_expression_cross_section(self) -> None:
        engine = SelectionEngine()
        df = pd.DataFrame(
            {"roe": [10.0, 15.0, 20.0, 8.0]},
            index=["A", "B", "C", "D"],
        )
        result = engine._evaluate_cross_section_expr("roe > 12", df, ["roe"])
        assert result.loc["A"] == 0.0
        assert result.loc["B"] == 1.0
        assert result.loc["C"] == 1.0
        assert result.loc["D"] == 0.0

    def test_expr_field_alias(self) -> None:
        engine = SelectionEngine()
        df = pd.DataFrame(
            {"cs_main_net_pct": [-0.1, 0.2, 0.0]},
            index=["A", "B", "C"],
        )
        result = engine._evaluate_cross_section_expr(
            "cs_main_net_pct > 0", df, ["cs_main_net_pct"],
        )
        assert result.loc["A"] == 0.0
        assert result.loc["B"] == 1.0
        assert result.loc["C"] == 0.0

    def test_nan_rows_do_not_fail_whole_series(self) -> None:
        engine = SelectionEngine()
        df = pd.DataFrame(
            {"pe_ttm": [10.0, float("nan"), 30.0]},
            index=["A", "B", "C"],
        )
        result = engine._evaluate_cross_section_expr(
            "pe_ttm > 0 and pe_ttm < 25", df, ["pe_ttm"],
        )
        assert result.loc["A"] == 1.0
        assert result.loc["B"] == 0.0
        assert result.loc["C"] == 0.0

    def test_resolve_selection_exprs_alias(self) -> None:
        score, bullish, bearish = SelectionEngine._resolve_selection_exprs(
            {"expr": "mom_20d > 0", "sell_expr": "mom_20d < -0.1"},
        )
        assert score == ""
        assert bullish == "mom_20d > 0"
        assert bearish == "mom_20d < -0.1"

    def test_evaluate_plugin_cross_section(self) -> None:
        engine = SelectionEngine()
        df = pd.DataFrame(
            {
                "mom_20d": [0.08, -0.03, 0.10],
                "barra_momentum": [0.02, -0.01, 0.03],
                "hist_vol_20": [0.30, 0.50, 0.25],
                "ep": [0.05, 0.02, 0.06],
                "cs_main_net_pct": [0.6, -0.01, 0.8],
                "rsi_14": [55.0, 80.0, 50.0],
                "boll_position": [0.5, 0.95, 0.3],
            },
            index=["600519.SH", "000001.SZ", "601318.SH"],
        )
        scores = engine._evaluate_cross_section_plugin(
            plugin_class=(
                "xqtrader.domain.trading.rules.plugins.multi_factor_resonance"
                ".MultiFactorResonancePlugin"
            ),
            cross_section_df=df,
            signal_date=date(2026, 6, 29),
            params={},
        )
        assert scores.loc["600519.SH"] > 0
        assert scores.loc["000001.SZ"] == 0.0
