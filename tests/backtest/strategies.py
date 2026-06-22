"""策略配置实例 — 预定义的策略配置"""

from .core import RuleConfig, StrategyConfig
from .sizer import PositionConfig

# ──────────────────────────────────────────────
# MACD 策略（无仓位插件，使用默认 95% 仓位）
# ──────────────────────────────────────────────

MACD_STRATEGY = StrategyConfig(
    strategy_id="macd",
    name="MACD 金叉死叉策略",
    rules=[
        RuleConfig(
            rule_id="macd_cross",
            rule_type="plugin",
            plugin_class="tests.backtest.plugins.macd.MACDPlugin",
            factor_ids=["macd", "signal", "hist", "hist_slope", "hist_area"],
            prev_factor_ids=["hist", "hist_area"],
        ),
    ],
)

# ──────────────────────────────────────────────
# MACD + 凯利仓位策略
# ──────────────────────────────────────────────

MACD_KELLY_STRATEGY = StrategyConfig(
    strategy_id="macd_kelly",
    name="MACD策略(凯利仓位)",
    rules=[
        RuleConfig(
            rule_id="macd_cross",
            rule_type="plugin",
            plugin_class="tests.backtest.plugins.macd.MACDPlugin",
            factor_ids=["macd", "signal", "hist", "hist_slope", "hist_area"],
            prev_factor_ids=["hist", "hist_area"],
        ),
    ],
    position_config=PositionConfig(
        plugin_class="tests.backtest.sizer.plugins.kelly.KellyPositionPlugin",
        params={"kelly_fraction": 0.5, "min_trades": 5, "default_pct": 0.2, "max_pct": 0.95},
    ),
)

# ──────────────────────────────────────────────
# MACD + ATR仓位策略
# ──────────────────────────────────────────────

MACD_ATR_STRATEGY = StrategyConfig(
    strategy_id="macd_atr",
    name="MACD策略(ATR仓位)",
    rules=[
        RuleConfig(
            rule_id="macd_cross",
            rule_type="plugin",
            plugin_class="tests.backtest.plugins.macd.MACDPlugin",
            factor_ids=["macd", "signal", "hist", "hist_slope", "hist_area"],
            prev_factor_ids=["hist", "hist_area"],
        ),
    ],
    position_config=PositionConfig(
        plugin_class="tests.backtest.sizer.plugins.atr_position.ATRPositionPlugin",
        params={"risk_pct": 0.02, "atr_multiplier": 2.0, "max_pct": 0.95},
        factor_ids=["atr"],
    ),
)

# ──────────────────────────────────────────────
# RSI 超买超卖策略（表达式规则）
# ──────────────────────────────────────────────

RSI_STRATEGY = StrategyConfig(
    strategy_id="rsi_obos",
    name="RSI 超买超卖策略",
    rules=[
        RuleConfig(
            rule_id="rsi_obos",
            rule_type="expression",
            factor_ids=["rsi"],
            buy_expr="rsi < 30",
            sell_expr="rsi > 70",
        ),
    ],
)
