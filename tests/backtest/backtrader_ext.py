"""Backtrader 扩展 — 动态因子数据源、PluginSizer、通用策略"""

import logging

import backtrader as bt
import pandas as pd

from .core import RuleContext, StrategyConfig
from .engine import SignalEngine
from .sizer import SizerEngine, PositionContext, PositionConfig

logger = logging.getLogger(__name__)


def create_factor_datafeed(df: pd.DataFrame, factor_ids: list[str],
                           fromdate: pd.Timestamp, todate: pd.Timestamp,
                           symbol: str = "") -> bt.feeds.PandasData:
    """根据因子列表动态创建 backtrader PandasData 数据源

    自动将 DataFrame 中的因子列声明为 backtrader lines，
    无需为每个策略硬编码 PandasData 子类。
    """
    lines_decl = tuple(factor_ids)
    params_decl = tuple((fid, fid) for fid in factor_ids)

    FactorPandasData = type(
        "FactorPandasData",
        (bt.feeds.PandasData,),
        {"lines": lines_decl, "params": params_decl},
    )

    data = FactorPandasData(
        dataname=df,
        fromdate=fromdate,
        todate=todate,
        datetime=None,
        open="open",
        high="high",
        low="low",
        close="close",
        volume="volume",
        openinterest=-1,
    )
    data._name = symbol
    return data


# ══════════════════════════════════════════════
# PluginSizer — backtrader Sizer 适配层
# ══════════════════════════════════════════════

class PluginSizer(bt.Sizer):
    """backtrader Sizer 适配层 — 委托给 SizerEngine 计算仓位

    职责仅限于:
      1. 将 backtrader 的 _getsizing 参数转换为 SizerEngine 的 PositionContext
      2. 将 SizerEngine 的 PositionResult 转换为 backtrader 要求的 int

    所有仓位计算逻辑由 SizerEngine（与 backtrader 解耦）完成。

    参数:
      - position_config: PositionConfig 实例（序列化为 dict 传递）
    """

    params = (
        ("position_config", None),  # PositionConfig 实例
    )

    def __init__(self):
        config = self.p.position_config
        self._engine = SizerEngine(config)

    def _getsizing(self, comminfo, cash, data, isbuy):
        """backtrader 原生 Sizer 接口 — 委托给 SizerEngine"""
        if not isbuy:
            return 0  # 卖出由策略通过 self.close() 处理

        # 从策略获取因子值和已平仓交易
        strat = self.strategy
        factor_values = getattr(strat, "_current_factor_values", {})
        closed_trades = getattr(strat, "_closed_trades", [])

        # 构造框架无关的 PositionContext
        ctx = PositionContext(
            symbol=data._name if hasattr(data, "_name") else "",
            current_price=data.close[0],
            available_cash=cash,
            portfolio_value=self.broker.getvalue(),
            factor_values=factor_values,
            closed_trades=closed_trades,
        )

        # 委托给 SizerEngine
        result = self._engine.calculate(ctx)
        return result.size


# ══════════════════════════════════════════════
# 通用策略
# ══════════════════════════════════════════════

class XqTraderStrategy(bt.Strategy):
    """XQ Trader 通用回测策略 — 通过 StrategyConfig 驱动，动态注入因子数据

    流程:
      1. 根据 strategy_config 获取所有规则所需的因子列表
      2. 动态从数据源读取因子值，注入 RuleContext
      3. SignalEngine 聚合多规则结果，产生交易信号
      4. self.buy() 不指定 size，由 PluginSizer（原生 Sizer）计算仓位
    """

    params = (
        ("strategy_config", None),  # StrategyConfig 实例
        ("print_log", True),
    )

    def __init__(self):
        config: StrategyConfig = self.params.strategy_config
        self.signal_engine = SignalEngine(config)
        self.trade_records: list[dict] = []
        self._closed_trades: list[dict] = []  # 已平仓交易记录（供仓位插件使用）
        self._current_factor_values: dict[str, float] = {}  # 当前因子值（供 Sizer 读取）

        # 从策略配置获取所需因子
        self._factor_ids = config.get_all_factor_ids()
        self._prev_factor_ids = config.get_all_prev_factor_ids()
        self._prev_factors: dict[str, float | None] = {
            f"{f}_prev": None for f in self._prev_factor_ids
        }

        # 跟踪未平仓的买入记录
        self._pending_buy: dict | None = None

    def log(self, txt: str, dt=None):
        if self.params.print_log:
            dt = dt or self.data.datetime.date(0)
            logger.info(f"[{dt}] {txt}")

    def _read_factor_values(self) -> dict[str, float]:
        """动态从数据源读取当前 bar 的所有因子值"""
        factor_values = {}
        for fid in self._factor_ids:
            try:
                line = getattr(self.data, fid, None)
                factor_values[fid] = line[0] if line is not None else None
            except (AttributeError, IndexError):
                factor_values[fid] = None

        # 注入前值
        factor_values.update(self._prev_factors)
        return factor_values

    def _update_prev_factors(self, factor_values: dict[str, float]):
        """更新需要缓存前值的因子"""
        for fid in self._prev_factor_ids:
            self._prev_factors[f"{fid}_prev"] = factor_values.get(fid)

    def next(self):
        current_date = self.data.datetime.date(0)
        close = self.data.close[0]

        # 动态读取因子值，保存到实例属性供 Sizer 读取
        factor_values = self._read_factor_values()
        self._current_factor_values = factor_values

        # 构造规则上下文
        context = RuleContext(
            symbol=self.data._name if hasattr(self.data, "_name") else "",
            signal_date=current_date,
            factor_values=factor_values,
        )

        result = self.signal_engine.execute(context)

        # 根据信号方向执行交易
        if result.direction == "buy" and not self.position:
            # 不指定 size，由 PluginSizer 自动计算
            self.buy()
            # 获取 Sizer 计算的实际 size
            size = self.sizer.getsizing(self.data, isbuy=True)
            self._pending_buy = {
                "date": current_date,
                "price": close,
                "size": size,
            }
            self.trade_records.append({
                "date": current_date,
                "action": "BUY",
                "price": close,
                "size": size,
                "reason": result.reason,
                "detail": result.detail,
            })
            self.log(f"BUY {size}@{close:.2f} | {result.reason}")

        elif result.direction == "sell" and self.position:
            size = self.position.size
            self.close()
            self.trade_records.append({
                "date": current_date,
                "action": "SELL",
                "price": close,
                "size": size,
                "reason": result.reason,
                "detail": result.detail,
            })
            self.log(f"SELL {size}@{close:.2f} | {result.reason}")

            # 记录已平仓交易（供仓位插件使用）
            if self._pending_buy is not None:
                pnl = (close - self._pending_buy["price"]) * size
                self._closed_trades.append({
                    "buy_date": self._pending_buy["date"],
                    "buy_price": self._pending_buy["price"],
                    "sell_date": current_date,
                    "sell_price": close,
                    "size": size,
                    "pnl": pnl,
                })
                self._pending_buy = None

        # 更新前值
        self._update_prev_factors(factor_values)

    def stop(self):
        self.log(f"策略结束，最终资金: {self.broker.getvalue():.2f}")
