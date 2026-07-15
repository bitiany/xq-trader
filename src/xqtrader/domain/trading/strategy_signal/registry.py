"""策略择时信号映射表 — strategy_name 到 SPI 插件 rule_id 的静态映射。

文档 §10.3 定义的 13 个策略（ExpressionPlugin 是通用引擎，非独立策略）。
strategy_name 是用户输入的友好名称，rule_id 是 OnDemandComputeRegistry 中
注册的 SPI 插件标识。category 用于策略分类展示。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyMeta:
    """策略元数据 — 映射 strategy_name 到 SPI 插件。"""

    strategy_name: str
    rule_id: str
    category: str  # trend / pattern / reversal


STRATEGY_REGISTRY: dict[str, StrategyMeta] = {
    "chanlun": StrategyMeta("chanlun", "ts_chanlun_signal", "reversal"),
    "td_sequential": StrategyMeta("td_sequential", "ts_td_sequential", "reversal"),
    "macd_cross": StrategyMeta("macd_cross", "macd", "trend"),
    "ma_cross": StrategyMeta("ma_cross", "ts_ma_cross", "trend"),
    "bollinger": StrategyMeta("bollinger", "ts_bollinger_break", "pattern"),
    "kdj": StrategyMeta("kdj", "ts_kdj_cross", "pattern"),
    "rsi_divergence": StrategyMeta("rsi_divergence", "ts_rsi_divergence", "reversal"),
    "adx_trend": StrategyMeta("adx_trend", "ts_adx_trend", "trend"),
    "bias_reversal": StrategyMeta("bias_reversal", "ts_bias_reversal", "reversal"),
    "momentum": StrategyMeta("momentum", "ts_momentum", "trend"),
    "volume_price": StrategyMeta("volume_price", "ts_volume_price", "trend"),
    "vol_ratio": StrategyMeta("vol_ratio", "ts_vol_ratio", "trend"),
    "donchian_turtle": StrategyMeta("donchian_turtle", "ts_donchian_turtle", "trend"),
}


def get_strategy_meta(strategy_name: str) -> StrategyMeta | None:
    """按 strategy_name 获取策略元数据。"""
    return STRATEGY_REGISTRY.get(strategy_name)


def list_strategy_names() -> list[str]:
    """列出全部可用策略名称（按字母排序）。"""
    return sorted(STRATEGY_REGISTRY.keys())
