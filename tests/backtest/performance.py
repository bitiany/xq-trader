"""绩效分析 — 基于 backtrader 内置 Analyzers

使用 backtrader 原生分析器，不自己造轮子:
  - TradeAnalyzer: 交易统计（次数、胜率、盈亏等）
  - DrawDown: 最大回撤
  - SharpeRatio: 夏普比率
  - Returns: 收益率
  - SQN: 系统质量数

交易记录（含信号依据）仍由 XqTraderStrategy.trade_records 跟踪，
因为 backtrader 不记录信号触发原因。
"""

import logging

import pandas as pd

import backtrader as bt

from .backtrader_ext import XqTraderStrategy

logger = logging.getLogger(__name__)


def add_analyzers(cerebro: bt.Cerebro):
    """向 Cerebro 添加内置分析器"""
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade_analyzer")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Days, riskfreerate=0.02, annualize=True, factor=252)
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.SQN, _name="sqn")


def extract_performance(strat: XqTraderStrategy, initial_cash: float) -> dict:
    """从 backtrader 分析器结果中提取绩效指标"""
    # ── TradeAnalyzer ──
    ta = strat.analyzers.trade_analyzer.get_analysis()
    total_trades = ta.get("total", {}).get("total", 0)
    won = ta.get("won", {}).get("total", 0)
    lost = ta.get("lost", {}).get("total", 0)
    win_rate = won / total_trades if total_trades > 0 else 0

    avg_win = ta.get("won", {}).get("pnl", {}).get("average", 0)
    avg_loss = abs(ta.get("lost", {}).get("pnl", {}).get("average", 0))
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else float("inf")

    max_win = ta.get("won", {}).get("pnl", {}).get("max", 0)
    max_loss = ta.get("lost", {}).get("pnl", {}).get("max", 0)

    # ── DrawDown ──
    dd = strat.analyzers.drawdown.get_analysis()
    max_drawdown = dd.get("max", {}).get("drawdown", 0)
    max_dd_len = dd.get("max", {}).get("len", 0)

    # ── SharpeRatio ──
    sharpe = strat.analyzers.sharpe.get_analysis().get("sharperatio", None)

    # ── Returns ──
    ret = strat.analyzers.returns.get_analysis()
    total_return = ret.get("rtot", 0)
    avg_return = ret.get("ravg", 0)

    # ── SQN ──
    sqn = strat.analyzers.sqn.get_analysis().get("sqn", None)

    # ── 最终资金 ──
    final_value = strat.broker.getvalue()

    return {
        "initial_cash": initial_cash,
        "final_value": round(final_value, 2),
        "total_return": f"{total_return:.2%}",
        "avg_daily_return": f"{avg_return:.4%}",
        "num_trades": total_trades,
        "win_trades": won,
        "loss_trades": lost,
        "win_rate": f"{win_rate:.2%}",
        "profit_loss_ratio": round(profit_loss_ratio, 2) if profit_loss_ratio != float("inf") else "N/A",
        "max_win": round(max_win, 2),
        "max_loss": round(max_loss, 2),
        "max_drawdown": f"{max_drawdown:.2f}%",
        "max_dd_length": max_dd_len,
        "sharpe_ratio": round(sharpe, 2) if sharpe is not None else "N/A",
        "sqn": round(sqn, 2) if sqn is not None else "N/A",
    }


def print_performance(perf: dict, strategy_name: str = ""):
    """打印绩效指标"""
    header = f"  回测绩效报告 — {strategy_name}" if strategy_name else "  回测绩效报告"
    lines = [
        "=" * 70,
        header,
        "=" * 70,
        f"  初始资金:       {perf['initial_cash']:>14,.2f}",
        f"  最终资金:       {perf['final_value']:>14,.2f}",
        f"  总收益率:       {perf['total_return']:>14}",
        f"  日均收益率:     {perf['avg_daily_return']:>14}",
        f"  交易次数:       {perf['num_trades']:>14}",
        f"  盈利次数:       {perf['win_trades']:>14}",
        f"  亏损次数:       {perf['loss_trades']:>14}",
        f"  胜率:           {perf['win_rate']:>14}",
        f"  盈亏比:         {str(perf['profit_loss_ratio']):>14}",
        f"  最大单笔盈利:   {perf['max_win']:>14,.2f}",
        f"  最大单笔亏损:   {perf['max_loss']:>14,.2f}",
        f"  最大回撤:       {perf['max_drawdown']:>14}",
        f"  最大回撤持续:   {perf['max_dd_length']:>14} 天",
        f"  夏普比率:       {str(perf['sharpe_ratio']):>14}",
        f"  SQN:            {str(perf['sqn']):>14}",
        "=" * 70,
    ]
    print("\n".join(lines))


def print_trade_records(strat: XqTraderStrategy):
    """打印交易记录（含信号触发依据和指标数值）— 每笔买卖独立行

    交易记录由 XqTraderStrategy.trade_records 跟踪，
    包含信号触发原因和因子数值，这是 backtrader 原生不提供的。
    """
    records = strat.trade_records
    if not records:
        logger.info("  无交易记录")
        return

    rows = []
    trade_idx = 0
    for r in records:
        if r["action"] == "BUY":
            trade_idx += 1
        rows.append({
            "序号": trade_idx,
            "日期": str(r["date"]),
            "方向": "买入" if r["action"] == "BUY" else "卖出",
            "价格": f"{r['price']:.2f}",
            "数量": r["size"],
            "信号依据": r["reason"],
        })
    df = pd.DataFrame(rows)
    lines = [
        "=" * 70,
        "  交易记录明细",
        "=" * 70,
        df.to_string(index=False),
        "=" * 70,
    ]
    print("\n".join(lines))
