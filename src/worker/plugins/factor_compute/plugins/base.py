"""FactorPlugin 基类与注册表 — 因子计算策略模式。

每个因子类别注册一个 FactorPlugin，BatchFactorEngine 遍历所有注册插件执行批量计算。
新因子通过注册表+插件机制接入，无需修改核心流程。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np
import pandas as pd


class FactorPlugin(ABC):
    """因子计算插件基类 — 策略模式。

    子类必须实现：
      - factor_ids: 该插件负责的因子ID列表
      - category: 因子类别
      - compute_batch(df, ctx): 批量计算（全量日期，返回 DataFrame）
    """

    @property
    @abstractmethod
    def factor_ids(self) -> list[str]:
        """该插件负责计算的因子ID列表。"""

    @property
    @abstractmethod
    def category(self) -> str:
        """因子类别: risk/fundamental/technical/quantitative/chan/candlestick/alpha"""

    @property
    def min_periods(self) -> int:
        """最少K线数，默认1。"""
        return 1

    @property
    def is_stateful(self) -> bool:
        """是否有状态因子 — 需要全部历史K线才能精确计算。

        有状态因子（如MACD/KDJ/EMA）使用 ewm() 递推，截断数据会导致初始值偏差。
        无状态因子只需固定窗口数据即可正确计算。
        """
        return False

    @property
    def dependencies(self) -> list[str]:
        """依赖的其他因子ID列表（按拓扑排序执行）。"""
        return []

    @abstractmethod
    def compute_batch(self, df: pd.DataFrame, ctx: dict[str, Any]) -> pd.DataFrame:
        """批量计算因子值 — 对单只股票的全部交易日一次性计算。

        利用 talib 对整个时间序列做向量化计算，避免逐日重复调用。

        Args:
            df: K线数据 DataFrame，包含 trade_date/open/close/high/low/volume/amount 列，
                按时间升序排列，覆盖该股票的全部历史或指定日期范围。
            ctx: 上下文字典，包含:
                - indicator_df: 日指标数据 DataFrame (sdc_daily_indicator)
                - fina_df: 财务指标 DataFrame (全部记录，按 ann_date 排序，供 merge_asof PIT 取值)
                - fund_flow_df: 资金流数据 DataFrame
                - index_kline_df: 指数K线 DataFrame (沪深300)
                - factor_values: 已计算的因子值（用于依赖因子，DataFrame 格式）
                - trade_dates: 需要输出的交易日列表

        Returns:
            DataFrame, columns=[trade_date, factor_id_1, factor_id_2, ...]
            每行对应一个交易日的因子值，仅包含 ctx["trade_dates"] 中的日期。
        """

    @staticmethod
    def safe_float(val: Any) -> float | None:
        """安全转换为 float，处理 NaN/Inf/None。

        所有插件共享此方法，禁止各插件重复实现 _safe_float。
        支持标量、numpy 数值、单元素 pd.Series。
        """
        if val is None:
            return None
        # 单元素 pd.Series：提取标量值
        if isinstance(val, pd.Series):
            if len(val) == 1:
                val = val.iloc[0]
            else:
                return None
        try:
            v = float(val)
            return v if not np.isnan(v) and not np.isinf(v) else None
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _filter_to_trade_dates(result_df: pd.DataFrame, trade_dates: list[Any]) -> pd.DataFrame:
        """将批量计算结果过滤到目标交易日。

        Args:
            result_df: 包含 trade_date 列的完整结果 DataFrame
            trade_dates: 需要保留的交易日列表

        Returns:
            仅包含目标交易日的 DataFrame
        """
        if not trade_dates or result_df.empty:
            return result_df
        td_set = set(trade_dates)
        mask = result_df["trade_date"].isin(td_set)
        return result_df[mask].copy()


class FactorPluginRegistry:
    """因子插件注册表 — 管理所有 FactorPlugin 实例。

    用法:
        registry = FactorPluginRegistry()
        registry.register(ValuationPlugin())
        registry.register(TechnicalPlugin())
        ...
        plugins = registry.resolve(["pe_ttm", "rsi_14"])
    """

    def __init__(self) -> None:
        self._plugins: list[FactorPlugin] = []
        self._factor_to_plugin: dict[str, FactorPlugin] = {}  # factor_id -> plugin

    def register(self, plugin: FactorPlugin) -> None:
        """注册一个因子插件。"""
        self._plugins.append(plugin)
        for fid in plugin.factor_ids:
            self._factor_to_plugin[fid] = plugin

    def resolve(self, factor_ids: list[str] | None = None) -> list[FactorPlugin]:
        """根据因子ID列表解析需要的插件（去重保序）。

        Args:
            factor_ids: 需要计算的因子ID列表，None 表示全部

        Returns:
            去重保序的 FactorPlugin 列表
        """
        if factor_ids is None:
            return list(self._plugins)

        seen: set[type] = set()
        result: list[FactorPlugin] = []
        for fid in factor_ids:
            plugin = self._factor_to_plugin.get(fid)
            if plugin and type(plugin) not in seen:
                seen.add(type(plugin))
                result.append(plugin)
        return result

    def get_plugin(self, factor_id: str) -> FactorPlugin | None:
        """获取因子ID对应的插件。"""
        return self._factor_to_plugin.get(factor_id)

    def all_factor_ids(self) -> list[str]:
        """获取所有已注册的因子ID。"""
        return list(self._factor_to_plugin.keys())

    def all_plugins(self) -> list[FactorPlugin]:
        """获取所有已注册的插件。"""
        return list(self._plugins)
