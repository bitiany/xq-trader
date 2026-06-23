"""回测运行器 — 通用回测流程封装

流程:
  1. 接收策略配置（已包含规则配置和仓位配置）
  2. 接收运行时入参：DataFrame、标的、日期范围、初始资金
  3. 基于策略规则，初始化信号引擎
  4. 构建 backtrader（含内置分析器和 PluginSizer）
  5. 执行并返回绩效结果

设计原则:
  - 策略配置（StrategyConfig）由 DB 加载，不含运行时参数
  - 运行时参数（df/symbol/start_date/end_date/cash 等）由调用方传入
"""

import backtrader as bt
import pandas as pd

from .backtrader_ext import PluginSizer, XqTraderStrategy, create_factor_datafeed
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
    """单标的回测入口

    Args:
        df: OHLCV + 因子数据 DataFrame，需含 trade_date 列以及策略所需的因子列
        strategy_config: 策略配置（含规则组、融合配置、仓位插件配置）
        symbol: 标的代码（用于日志和回测元数据）
        start_date: 回测开始日期 (YYYY-MM-DD)
        end_date: 回测结束日期 (YYYY-MM-DD)
        cash: 初始资金
        commission: 手续费率

    Returns:
        绩效指标字典（见 extract_performance）
    """
    bt_df = df.copy()
    bt_df = bt_df.set_index("trade_date")
    bt_df.index = pd.DatetimeIndex(bt_df.index)
    bt_df.columns = [c.lower() for c in bt_df.columns]

    required = ["open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in bt_df.columns]
    if missing:
        raise ValueError(f"回测数据缺少必要列: {missing}")

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
    perf["equity_curve"] = [
        {"date": str(item["date"]), "value": item["value"]}
        for item in strat.equity_curve
    ]
    perf["trades"] = [
        {**item, "date": str(item["date"])}
        for item in strat.trade_records
    ]
    perf["positions"] = [
        {**item, "date": str(item["date"])}
        for item in strat.position_snapshots
    ]
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    ohlcv_df = bt_df.loc[start_ts:end_ts].reset_index()
    perf["ohlcv"] = [
        {
            "date": str(pd.Timestamp(item["trade_date"]).date()),
            "open": float(item["open"]),
            "high": float(item["high"]),
            "low": float(item["low"]),
            "close": float(item["close"]),
            "volume": float(item["volume"]),
        }
        for item in ohlcv_df.to_dict("records")
    ]
    print_performance(perf, strategy_config.name)
    print_trade_records(strat)

    return perf
