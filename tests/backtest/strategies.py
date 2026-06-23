"""策略配置实例 — 测试用预定义策略

所有策略配置都不包含运行时参数（标的、日期、资金等），
仅描述策略规则、融合方式和仓位插件，由 API 入参在运行时注入运行参数。
"""

from xqtrader.domain.trading.backtest import (
    FusionConfig,
    PositionConfig,
    RuleConfig,
    RuleGroupConfig,
    StrategyConfig,
)

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
            plugin_class="xqtrader.domain.trading.backtest.plugins.macd.MACDPlugin",
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
            plugin_class="xqtrader.domain.trading.backtest.plugins.macd.MACDPlugin",
            factor_ids=["macd", "signal", "hist", "hist_slope", "hist_area"],
            prev_factor_ids=["hist", "hist_area"],
        ),
    ],
    position_config=PositionConfig(
        plugin_class="xqtrader.domain.trading.backtest.sizer.plugins.kelly.KellyPositionPlugin",
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
            plugin_class="xqtrader.domain.trading.backtest.plugins.macd.MACDPlugin",
            factor_ids=["macd", "signal", "hist", "hist_slope", "hist_area"],
            prev_factor_ids=["hist", "hist_area"],
        ),
    ],
    position_config=PositionConfig(
        plugin_class="xqtrader.domain.trading.backtest.sizer.plugins.atr_position.ATRPositionPlugin",
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


# ══════════════════════════════════════════════
# 多规则融合策略
# ══════════════════════════════════════════════

# ──────────────────────────────────────────────
# 场景一: RSI + BIAS AND 融合（单组双规则）
# ──────────────────────────────────────────────

RSI_BIAS_AND_STRATEGY = StrategyConfig(
    strategy_id="rsi_bias_and",
    name="RSI+BIAS AND融合策略",
    groups=[
        RuleGroupConfig(
            group_id="reversal",
            name="反转组",
            rules=[
                RuleConfig(
                    rule_id="rsi_obos",
                    rule_type="expression",
                    factor_ids=["rsi"],
                    buy_expr="rsi < 35",
                    sell_expr="rsi > 65",
                ),
                RuleConfig(
                    rule_id="bias_reversal",
                    rule_type="expression",
                    factor_ids=["bias"],
                    buy_expr="bias < -3",
                    sell_expr="bias > 3",
                ),
            ],
            fusion=FusionConfig(method="and"),
        ),
    ],
)


# ──────────────────────────────────────────────
# 场景一变体: RSI + BIAS 加权评分融合
# ──────────────────────────────────────────────

RSI_BIAS_WEIGHTED_STRATEGY = StrategyConfig(
    strategy_id="rsi_bias_weighted",
    name="RSI+BIAS 加权评分策略",
    groups=[
        RuleGroupConfig(
            group_id="reversal",
            name="反转组",
            rules=[
                RuleConfig(
                    rule_id="rsi_obos",
                    rule_type="expression",
                    factor_ids=["rsi"],
                    buy_expr="rsi < 35",
                    sell_expr="rsi > 65",
                ),
                RuleConfig(
                    rule_id="bias_reversal",
                    rule_type="expression",
                    factor_ids=["bias"],
                    buy_expr="bias < -3",
                    sell_expr="bias > 3",
                ),
            ],
            fusion=FusionConfig(
                method="weighted_score",
                weights={"rsi_obos": 0.6, "bias_reversal": 0.4},
                buy_threshold=0.3,
                sell_threshold=0.3,
            ),
        ),
    ],
)


# ──────────────────────────────────────────────
# 场景一变体: MACD + RSI 加权投票融合
# ──────────────────────────────────────────────

MACD_RSI_VOTE_STRATEGY = StrategyConfig(
    strategy_id="macd_rsi_vote",
    name="MACD+RSI 加权投票策略",
    groups=[
        RuleGroupConfig(
            group_id="mixed",
            name="混合组",
            rules=[
                RuleConfig(
                    rule_id="macd_cross",
                    rule_type="plugin",
                    plugin_class="xqtrader.domain.trading.backtest.plugins.macd.MACDPlugin",
                    factor_ids=["macd", "signal", "hist", "hist_slope", "hist_area"],
                    prev_factor_ids=["hist", "hist_area"],
                ),
                RuleConfig(
                    rule_id="rsi_obos",
                    rule_type="expression",
                    factor_ids=["rsi"],
                    buy_expr="rsi < 35",
                    sell_expr="rsi > 65",
                ),
            ],
            fusion=FusionConfig(
                method="weighted_vote",
                weights={"macd_cross": 0.6, "rsi_obos": 0.4},
                buy_threshold=0.5,
                sell_threshold=0.5,
            ),
        ),
    ],
)


# ──────────────────────────────────────────────
# 场景一变体: RSI + BIAS + MON_5D IC 加权融合
# ──────────────────────────────────────────────

IC_WEIGHTED_STRATEGY = StrategyConfig(
    strategy_id="ic_weighted",
    name="IC加权融合策略",
    groups=[
        RuleGroupConfig(
            group_id="ic_group",
            name="IC加权组",
            rules=[
                RuleConfig(
                    rule_id="rsi_obos",
                    rule_type="expression",
                    factor_ids=["rsi"],
                    buy_expr="rsi < 35",
                    sell_expr="rsi > 65",
                ),
                RuleConfig(
                    rule_id="bias_reversal",
                    rule_type="expression",
                    factor_ids=["bias"],
                    buy_expr="bias < -3",
                    sell_expr="bias > 3",
                ),
                RuleConfig(
                    rule_id="mon_5d",
                    rule_type="expression",
                    factor_ids=["mon_5d"],
                    buy_expr="mon_5d > 0.02",
                    sell_expr="mon_5d < -0.02",
                ),
            ],
            fusion=FusionConfig(
                method="ic_weighted",
                weights={"rsi_obos": 0.05, "bias_reversal": 0.03, "mon_5d": 0.04},
                buy_threshold=0.02,
                sell_threshold=0.02,
            ),
        ),
    ],
)


# ──────────────────────────────────────────────
# 场景二: 多规则组嵌套（反转组 + 动量组，组间 OR 融合）
# ──────────────────────────────────────────────

MULTI_GROUP_STRATEGY = StrategyConfig(
    strategy_id="multi_group",
    name="多规则组嵌套策略(反转+动量)",
    groups=[
        RuleGroupConfig(
            group_id="reversal_group",
            name="反转组(RSI+BIAS)",
            rules=[
                RuleConfig(
                    rule_id="rsi_obos",
                    rule_type="expression",
                    factor_ids=["rsi"],
                    buy_expr="rsi < 35",
                    sell_expr="rsi > 65",
                ),
                RuleConfig(
                    rule_id="bias_reversal",
                    rule_type="expression",
                    factor_ids=["bias"],
                    buy_expr="bias < -3",
                    sell_expr="bias > 3",
                ),
            ],
            fusion=FusionConfig(method="and"),
        ),
        RuleGroupConfig(
            group_id="momentum_group",
            name="动量组(MON_5D)",
            rules=[
                RuleConfig(
                    rule_id="mon_5d",
                    rule_type="expression",
                    factor_ids=["mon_5d"],
                    buy_expr="mon_5d > 0.03",
                    sell_expr="mon_5d < -0.03",
                ),
            ],
            fusion=FusionConfig(method="or"),
        ),
    ],
    group_fusion=FusionConfig(method="or"),
)


# ──────────────────────────────────────────────
# 场景二变体: 多规则组嵌套（反转组 + 动量组，组间加权投票）
# ──────────────────────────────────────────────

MULTI_GROUP_VOTE_STRATEGY = StrategyConfig(
    strategy_id="multi_group_vote",
    name="多规则组嵌套策略(组间加权投票)",
    groups=[
        RuleGroupConfig(
            group_id="reversal_group",
            name="反转组(RSI+BIAS)",
            rules=[
                RuleConfig(
                    rule_id="rsi_obos",
                    rule_type="expression",
                    factor_ids=["rsi"],
                    buy_expr="rsi < 35",
                    sell_expr="rsi > 65",
                ),
                RuleConfig(
                    rule_id="bias_reversal",
                    rule_type="expression",
                    factor_ids=["bias"],
                    buy_expr="bias < -3",
                    sell_expr="bias > 3",
                ),
            ],
            fusion=FusionConfig(method="and"),
        ),
        RuleGroupConfig(
            group_id="momentum_group",
            name="动量组(MON_5D)",
            rules=[
                RuleConfig(
                    rule_id="mon_5d",
                    rule_type="expression",
                    factor_ids=["mon_5d"],
                    buy_expr="mon_5d > 0.02",
                    sell_expr="mon_5d < -0.02",
                ),
            ],
            fusion=FusionConfig(method="or"),
        ),
    ],
    group_fusion=FusionConfig(
        method="weighted_vote",
        weights={"reversal_group": 0.6, "momentum_group": 0.4},
        buy_threshold=0.35,
        sell_threshold=0.35,
    ),
)
