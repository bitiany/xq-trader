"""回测引擎共享常量。"""

from pathlib import Path

# 交易日天数（年化计算用）
TRADING_DAYS_PER_YEAR: int = 252

# HTML 报告输出目录
REPORT_DIR: Path = Path("reports/backtest")
