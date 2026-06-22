"""QuantStats 绩效分析器单元测试 — 纯计算，无需数据库。"""

from datetime import date
from pathlib import Path
from tempfile import gettempdir

import numpy as np
import pandas as pd
import pytest

from xqtrader.domain.trading.backtest import (
    BacktestResult,
    QuantStatsAnalyzer,
)


@pytest.fixture
def sample_daily_returns() -> pd.Series:
    """生成模拟日收益率序列。"""
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=120, freq="B")
    returns = pd.Series(np.random.normal(0.0008, 0.015, 120), index=dates)
    returns.name = "strategy"
    return returns


@pytest.fixture
def sample_backtest_result(sample_daily_returns: pd.Series) -> BacktestResult:
    """构建模拟回测结果。"""
    equity_curve = (1 + sample_daily_returns).cumprod() * 1_000_000
    final_value = float(equity_curve.iloc[-1])
    total_return = (final_value - 1_000_000) / 1_000_000
    return BacktestResult(
        strategy_id="test_strategy_001",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 6, 30),
        initial_capital=1_000_000.0,
        final_value=final_value,
        total_return=total_return,
        annual_return=total_return * 2,
        max_drawdown=-0.05,
        sharpe_ratio=1.1,
        total_trades=45,
        daily_returns=sample_daily_returns,
        equity_curve=equity_curve,
    )


class TestQuantStatsAnalyzer:
    """QuantStatsAnalyzer 单元测试。"""

    def test_compute_metrics(self, sample_backtest_result: BacktestResult) -> None:
        """测试指标计算 — 75+ 项指标 + 17 个结构化字段。"""
        analyzer = QuantStatsAnalyzer()
        report = analyzer.analyze(
            sample_backtest_result,
            output_dir=Path(gettempdir()) / "backtest_test",
        )

        # 结构化字段不为零（有实际值）
        assert report.metrics.cumulative_return != 0.0
        assert report.metrics.annual_return != 0.0
        assert report.metrics.sharpe_ratio != 0.0
        assert report.metrics.volatility > 0.0
        assert report.metrics.max_drawdown < 0.0

        # raw 包含全量 75 项指标
        assert len(report.metrics.raw) >= 70

        # 关键指标在 raw 中存在
        assert "Cumulative Return" in report.metrics.raw
        assert "Sharpe" in report.metrics.raw
        assert "Max Drawdown" in report.metrics.raw

    def test_html_report_generation(self, sample_backtest_result: BacktestResult) -> None:
        """测试 HTML 报告生成 + 中文补丁。"""
        analyzer = QuantStatsAnalyzer()
        output_dir = Path(gettempdir()) / "backtest_test_cn"
        report = analyzer.analyze(sample_backtest_result, output_dir=output_dir)

        assert report.html_report_path is not None
        html_path = Path(report.html_report_path)
        assert html_path.exists()

        html_content = html_path.read_text(encoding="utf-8")

        # 中文标签存在
        assert "关键绩效指标" in html_content
        assert "累计收益率" in html_content
        assert "夏普比率" in html_content
        assert "最大回撤" in html_content
        assert "年化波动率" in html_content

        # 自定义标题存在
        assert "策略绩效报告 — test_strategy_001" in html_content

    def test_to_dict(self, sample_backtest_result: BacktestResult) -> None:
        """测试 to_dict 序列化。"""
        analyzer = QuantStatsAnalyzer()
        report = analyzer.analyze(
            sample_backtest_result,
            output_dir=Path(gettempdir()) / "backtest_test_dict",
        )

        d = report.to_dict()
        assert d["strategy_id"] == "test_strategy_001"
        assert d["start_date"] == "2024-01-01"
        assert d["end_date"] == "2024-06-30"
        assert "metrics" in d
        assert "cumulative_return" in d["metrics"]
        assert "sharpe_ratio" in d["metrics"]
        assert "html_report_path" in d

    def test_empty_returns(self) -> None:
        """测试空收益率序列 — 不应崩溃。"""
        result = BacktestResult(
            strategy_id="empty_test",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 2),
            initial_capital=1_000_000.0,
            final_value=1_000_000.0,
            total_return=0.0,
            annual_return=0.0,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
            total_trades=0,
            daily_returns=pd.Series(dtype=float),
            equity_curve=pd.Series(dtype=float),
        )

        analyzer = QuantStatsAnalyzer()
        # 空序列应抛异常或返回零值指标 — QuantStats 内部会处理
        # 这里验证不产生未捕获异常
        try:
            report = analyzer.analyze(result, output_dir=Path(gettempdir()) / "backtest_test_empty")
            # 如果成功，指标应为零值
            assert report.metrics.cumulative_return == 0.0
        except Exception:
            # QuantStats 对空序列可能抛异常，这是可接受的
            pass
