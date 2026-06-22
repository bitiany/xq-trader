"""回测运行器 — 通用回测流程封装

流程:
  1. 获取策略配置（已包含规则配置和仓位配置）
  2. 准备标的数据
  3. 基于策略规则，初始化信号引擎
  4. 构建 backtrader（含内置分析器和 PluginSizer）
  5. 执行
"""

import backtrader as bt
import pandas as pd

from .backtrader_ext import XqTraderStrategy, PluginSizer, create_factor_datafeed
from .core import StrategyConfig
from .performance import add_analyzers, extract_performance, print_performance, print_trade_records

DEFAULT_CASH = 1000000
DEFAULT_COMMISSION = 0.0003


def run_backtest(
    df: pd.DataFrame,
    strategy_config: StrategyConfig,
    *,
    symbol: str = "",
    start_date: str = "",
    end_date: str = "",
    cash: float = DEFAULT_CASH,
    commission: float = DEFAULT_COMMISSION,
) -> dict:
    bt_df = df.copy()
    bt_df = bt_df.set_index("trade_date")
    bt_df.columns = [c.lower() for c in bt_df.columns]

    required = ["open", "high", "low", "close", "volume"]
    for col in required:
        assert col in bt_df.columns, f"缺少必要列: {col}"

    # 从策略配置获取所需因子列表，动态创建数据源
    factor_ids = strategy_config.get_all_factor_ids()
    data = create_factor_datafeed(
        df=bt_df,
        factor_ids=factor_ids,
        fromdate=pd.Timestamp(start_date),
        todate=pd.Timestamp(end_date),
        symbol=symbol,
    )

    # 构建 backtrader
    cerebro = bt.Cerebro(stdstats=False, preload=True, runonce=False)
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=commission)
    cerebro.adddata(data)

    # 添加策略
    strat_idx = cerebro.addstrategy(XqTraderStrategy, strategy_config=strategy_config)

    # 根据 PositionConfig 添加 PluginSizer（原生 Sizer 机制）
    # PluginSizer 内部委托给 SizerEngine，SizerEngine 路由到具体仓位插件
    cerebro.addsizer_byidx(
        strat_idx,
        PluginSizer,
        position_config=strategy_config.position_config,
    )

    # 添加内置分析器
    add_analyzers(cerebro)

    # 执行回测
    strategies = cerebro.run()
    strat = strategies[0]

    # 提取并打印绩效
    perf = extract_performance(strat, initial_cash=cash)
    print_performance(perf, strategy_config.name)
    print_trade_records(strat)

    return perf
