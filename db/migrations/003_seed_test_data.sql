-- ============================================================
-- 预置时序策略种子数据（JSONB 策略配置）
-- ============================================================

BEGIN;

-- 当前轻量回测支持的时序规则：表达式规则 + backtest 插件规则
INSERT INTO trading.td_rule_registry (
  rule_id, name, description, category, rule_type, definition, factors, is_builtin, status
)
VALUES
(
  'ts_macd_cross',
  'MACD 金叉死叉',
  'MACD 柱线由负转正买入，由正转负卖出，并结合柱线斜率与面积增强信号。',
  'timing',
  'plugin',
  '{"plugin_class": "xqtrader.domain.trading.backtest.plugins.macd.MACDPlugin", "default_params": {}}'::jsonb,
  '["macd", "signal", "hist", "hist_slope", "hist_area"]'::jsonb,
  true,
  'active'
),
(
  'ts_rsi_obos',
  'RSI 超买超卖',
  'RSI 小于 30 买入，大于 70 卖出。',
  'timing',
  'expression',
  '{"buy_expr": "rsi < 30", "sell_expr": "rsi > 70"}'::jsonb,
  '["rsi"]'::jsonb,
  true,
  'active'
),
(
  'ts_rsi_reversion_expr',
  'RSI 均值回归',
  'RSI 小于 35 买入，大于 65 卖出。',
  'timing',
  'expression',
  '{"buy_expr": "rsi < 35", "sell_expr": "rsi > 65"}'::jsonb,
  '["rsi"]'::jsonb,
  true,
  'active'
),
(
  'ts_bias_reversal',
  'BIAS 乖离反转',
  'BIAS 小于 -3 买入，大于 3 卖出。',
  'timing',
  'expression',
  '{"buy_expr": "bias < -3", "sell_expr": "bias > 3"}'::jsonb,
  '["bias"]'::jsonb,
  true,
  'active'
),
(
  'ts_momentum_5d',
  '5日动量',
  '5 日动量大于 2% 买入，小于 -2% 卖出。',
  'timing',
  'expression',
  '{"buy_expr": "mon_5d > 0.02", "sell_expr": "mon_5d < -0.02"}'::jsonb,
  '["mon_5d"]'::jsonb,
  true,
  'active'
)
ON CONFLICT (rule_id) DO UPDATE SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  category = EXCLUDED.category,
  rule_type = EXCLUDED.rule_type,
  definition = EXCLUDED.definition,
  factors = EXCLUDED.factors,
  is_builtin = EXCLUDED.is_builtin,
  status = EXCLUDED.status;

-- 删除旧 SPI 规则：这些规则依赖已删除的旧 rules.plugins 技术信号体系
DELETE FROM trading.td_rule_registry
WHERE rule_id IN (
  'ts_macd_trend',
  'ts_bollinger_band',
  'ts_ma_cross',
  'ts_donchian_breakout',
  'ts_kdj_cross',
  'ts_atr_trailing_stop',
  'ts_chan_buy_sell',
  'ts_rsi_reversion',
  'ts_momentum_long',
  'ts_rsi_overbought'
);

-- 清理旧方案产生的乱码/不可运行预置时序策略
DELETE FROM trading.td_strategy
WHERE strategy_id IN (
  'ts_atr_trailing_stop',
  'ts_chan_buy_sell',
  'ts_boll_breakout',
  'ts_macd_acceleration',
  'ts_boll_mean_reversion',
  'ts_rsi_reversion',
  'ts_dual_ma_trend',
  'ts_donchian_turtle',
  'ts_kdj_reversal',
  'ts_multi_signal_timing'
);

INSERT INTO trading.td_strategy (
  strategy_id, name, description, strategy_type, config, status
)
VALUES
(
  'test_macd_rsi',
  'MACD+RSI 加权投票策略',
  'MACD 金叉死叉与 RSI 超买超卖的加权投票时序策略。',
  'timing',
  '{
    "groups": [
      {
        "group_id": "mixed",
        "name": "MACD+RSI 混合组",
        "rules": [
          {"rule_id": "ts_macd_cross", "weight": 0.6},
          {"rule_id": "ts_rsi_reversion_expr", "weight": 0.4}
        ],
        "fusion": {
          "method": "weighted_vote",
          "weights": {"ts_macd_cross": 0.6, "ts_rsi_reversion_expr": 0.4},
          "buy_threshold": 0.5,
          "sell_threshold": 0.5
        }
      }
    ],
    "group_fusion": {"method": "or"}
  }'::jsonb,
  'active'
),
(
  'ts_macd_cross',
  'MACD 金叉死叉策略',
  '基于 MACD 柱线翻转、斜率和面积变化的趋势择时策略。',
  'timing',
  '{
    "groups": [
      {
        "group_id": "macd_group",
        "name": "MACD 信号组",
        "rules": [{"rule_id": "ts_macd_cross", "weight": 1.0}],
        "fusion": {"method": "or", "buy_threshold": 0.5, "sell_threshold": 0.5}
      }
    ],
    "group_fusion": {"method": "or"}
  }'::jsonb,
  'active'
),
(
  'ts_rsi_obos',
  'RSI 超买超卖策略',
  'RSI 小于 30 买入，大于 70 卖出的时序策略。',
  'timing',
  '{
    "groups": [
      {
        "group_id": "rsi_group",
        "name": "RSI 信号组",
        "rules": [{"rule_id": "ts_rsi_obos", "weight": 1.0}],
        "fusion": {"method": "or", "buy_threshold": 0.5, "sell_threshold": 0.5}
      }
    ],
    "group_fusion": {"method": "or"}
  }'::jsonb,
  'active'
),
(
  'ts_rsi_bias_and',
  'RSI+BIAS AND 融合策略',
  'RSI 反转与 BIAS 乖离同时满足时触发交易信号。',
  'timing',
  '{
    "groups": [
      {
        "group_id": "reversal_group",
        "name": "反转信号组",
        "rules": [
          {"rule_id": "ts_rsi_reversion_expr", "weight": 1.0},
          {"rule_id": "ts_bias_reversal", "weight": 1.0}
        ],
        "fusion": {"method": "and", "buy_threshold": 0.5, "sell_threshold": 0.5}
      }
    ],
    "group_fusion": {"method": "or"}
  }'::jsonb,
  'active'
),
(
  'ts_rsi_bias_weighted',
  'RSI+BIAS 加权评分策略',
  'RSI 反转与 BIAS 乖离按 0.6/0.4 权重进行加权评分融合。',
  'timing',
  '{
    "groups": [
      {
        "group_id": "weighted_reversal_group",
        "name": "加权反转组",
        "rules": [
          {"rule_id": "ts_rsi_reversion_expr", "weight": 0.6},
          {"rule_id": "ts_bias_reversal", "weight": 0.4}
        ],
        "fusion": {
          "method": "weighted_score",
          "weights": {"ts_rsi_reversion_expr": 0.6, "ts_bias_reversal": 0.4},
          "buy_threshold": 0.5,
          "sell_threshold": 0.5
        }
      }
    ],
    "group_fusion": {"method": "or"}
  }'::jsonb,
  'active'
),
(
  'ts_multi_group_momentum',
  '反转+动量多规则组策略',
  'RSI+BIAS 反转组与 5 日动量组分层融合，组间 OR 触发。',
  'timing',
  '{
    "groups": [
      {
        "group_id": "reversal_group",
        "name": "反转组(RSI+BIAS)",
        "rules": [
          {"rule_id": "ts_rsi_reversion_expr", "weight": 1.0},
          {"rule_id": "ts_bias_reversal", "weight": 1.0}
        ],
        "fusion": {"method": "and", "buy_threshold": 0.5, "sell_threshold": 0.5}
      },
      {
        "group_id": "momentum_group",
        "name": "动量组",
        "rules": [{"rule_id": "ts_momentum_5d", "weight": 1.0}],
        "fusion": {"method": "or", "buy_threshold": 0.5, "sell_threshold": 0.5}
      }
    ],
    "group_fusion": {
      "method": "or",
      "weights": {"reversal_group": 0.6, "momentum_group": 0.4},
      "buy_threshold": 0.5,
      "sell_threshold": 0.5
    }
  }'::jsonb,
  'active'
)
ON CONFLICT (strategy_id) DO UPDATE SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  strategy_type = EXCLUDED.strategy_type,
  config = EXCLUDED.config,
  status = EXCLUDED.status;

COMMIT;
