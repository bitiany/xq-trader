-- ============================================================
-- 预置选股策略种子数据
-- 因子来源（参考 docs/factor-architecture.md, docs/factor-catalog.md）:
--   stock.fac_factor_value — 逐标的因子 (mom_20d, hist_vol_20, rsi_14, boll_position, cs_main_net_pct)
--   stock.sdc_daily_indicator — 每日估值指标 (pe_ttm, pb, dv_ratio; 衍生: ep=1/pe_ttm, bp=1/pb)
--   stock.sdc_financial_indicator — 季频财务指标 (roe, grossprofit_margin, roa)
-- ============================================================

-- ==================== 规则注册表 ====================

-- 巴菲特价值投资 - 价值过滤: PE_TTM > 0 且 < 25
INSERT INTO trading.td_rule_registry (rule_id, name, category, type, expression, factors, signal_mapping, default_config, description, is_builtin, status)
VALUES (
  'cs_value_filter', '价值过滤', 'cross_section', 'expression',
  'pe_ttm > 0 and pe_ttm < 25',
  '["pe_ttm"]',
  '{"true": {"direction": "long", "confidence": 0.6}, "false": {"direction": "neutral", "confidence": 0.0}}',
  '{}',
  'PE_TTM在0-25之间', true, 'active'
) ON CONFLICT (rule_id) DO NOTHING;

-- 巴菲特价值投资 - 质量过滤: ROE > 12 且 销售毛利率 > 30
-- 注意: grossprofit_margin 是百分比(销售毛利率), gross_margin 是绝对值(毛利)
INSERT INTO trading.td_rule_registry (rule_id, name, category, type, expression, factors, signal_mapping, default_config, description, is_builtin, status)
VALUES (
  'cs_quality_filter', '质量过滤', 'cross_section', 'expression',
  'roe > 12 and grossprofit_margin > 30',
  '["roe", "grossprofit_margin"]',
  '{"true": {"direction": "long", "confidence": 0.7}, "false": {"direction": "neutral", "confidence": 0.0}}',
  '{}',
  'ROE>12%且销售毛利率>30%', true, 'active'
) ON CONFLICT (rule_id) DO NOTHING;

-- 低波过滤: hist_vol_20 < 0.35
INSERT INTO trading.td_rule_registry (rule_id, name, category, type, expression, factors, signal_mapping, default_config, description, is_builtin, status)
VALUES (
  'cs_low_volatility', '低波过滤', 'cross_section', 'expression',
  'hist_vol_20 < 0.35',
  '["hist_vol_20"]',
  '{"true": {"direction": "long", "confidence": 0.5}, "false": {"direction": "neutral", "confidence": 0.0}}',
  '{}',
  '20日历史波动率 < 35%', true, 'active'
) ON CONFLICT (rule_id) DO NOTHING;

-- 动量过滤: mom_20d > 0
INSERT INTO trading.td_rule_registry (rule_id, name, category, type, expression, factors, signal_mapping, default_config, description, is_builtin, status)
VALUES (
  'cs_momentum_filter', '动量过滤', 'cross_section', 'expression',
  'mom_20d > 0',
  '["mom_20d"]',
  '{"true": {"direction": "long", "confidence": 0.6}, "false": {"direction": "neutral", "confidence": 0.0}}',
  '{}',
  '20日动量为正', true, 'active'
) ON CONFLICT (rule_id) DO NOTHING;

-- 资金流过滤: cs_main_net_pct > 0
INSERT INTO trading.td_rule_registry (rule_id, name, category, type, expression, factors, signal_mapping, default_config, description, is_builtin, status)
VALUES (
  'cs_fund_flow_filter', '资金流过滤', 'cross_section', 'expression',
  'cs_main_net_pct > 0',
  '["cs_main_net_pct"]',
  '{"true": {"direction": "long", "confidence": 0.5}, "false": {"direction": "neutral", "confidence": 0.0}}',
  '{}',
  '主力净流入占比为正', true, 'active'
) ON CONFLICT (rule_id) DO NOTHING;

-- 多因子共振 - SPI 插件
-- 因子: ep(盈利收益率=1/pe_ttm, 衍生自sdc_daily_indicator) + 技术因子(来自fac_factor_value)
INSERT INTO trading.td_rule_registry (rule_id, name, category, type, spi_class, factors, default_config, description, is_builtin, status)
VALUES (
  'cs_multi_factor_resonance', '多因子共振', 'cross_section', 'spi',
  'xqtrader.domain.trading.rules.plugins.multi_factor_resonance.MultiFactorResonancePlugin',
  '["mom_20d", "hist_vol_20", "ep", "cs_main_net_pct", "rsi_14", "boll_position"]',
  '{"min_resonance_dims": 3}',
  '动量+价值+资金流+技术面多维度共振确认', true, 'active'
) ON CONFLICT (rule_id) DO NOTHING;

-- ==================== 规则-因子依赖 ====================

INSERT INTO trading.td_rule_factor_dep (rule_id, factor_id, usage) VALUES
  ('cs_value_filter', 'pe_ttm', '价值维度'),
  ('cs_quality_filter', 'roe', '质量维度'),
  ('cs_quality_filter', 'grossprofit_margin', '质量维度'),
  ('cs_low_volatility', 'hist_vol_20', '低波维度'),
  ('cs_momentum_filter', 'mom_20d', '动量维度'),
  ('cs_fund_flow_filter', 'cs_main_net_pct', '资金流维度'),
  ('cs_multi_factor_resonance', 'mom_20d', '动量维度'),
  ('cs_multi_factor_resonance', 'hist_vol_20', '低波维度'),
  ('cs_multi_factor_resonance', 'ep', '价值维度'),
  ('cs_multi_factor_resonance', 'cs_main_net_pct', '资金流维度'),
  ('cs_multi_factor_resonance', 'rsi_14', '技术面维度'),
  ('cs_multi_factor_resonance', 'boll_position', '技术面维度')
ON CONFLICT DO NOTHING;

-- ==================== 策略1: 巴菲特价值投资 ====================
-- 价值+质量+低波三因子筛选，阈值0.5（至少满足2个规则）

INSERT INTO trading.td_strategy (strategy_id, name, description, cross_section_config, time_series_config, position_sizing_config, risk_overrides, universe_pool, status)
VALUES (
  'buffett_value', '巴菲特价值投资',
  '价值+质量+低波三因子筛选',
  '{"method": "weighted_score", "threshold": 0.5}',
  '{}',
  '{"strategy": "equal_weight", "max_total_weight": 0.95}',
  '{"max_position_pct": 0.10, "max_positions": 10}',
  'idx_300', 'active'
) ON CONFLICT (strategy_id) DO NOTHING;

-- 截面规则组
INSERT INTO trading.td_strategy_rule_group (strategy_id, group_type, combination_method, combination_params, threshold)
SELECT id, 'cross_section', 'weighted_score', '{"threshold": 0.5}', 0.5
FROM trading.td_strategy WHERE strategy_id = 'buffett_value';

-- 规则绑定: 价值0.4 + 质量0.4 + 低波0.2
INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_value_filter', 0.4, '{}', 1
FROM trading.td_strategy_rule_group g
JOIN trading.td_strategy s ON g.strategy_id = s.id
WHERE s.strategy_id = 'buffett_value' AND g.group_type = 'cross_section';

INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_quality_filter', 0.4, '{}', 2
FROM trading.td_strategy_rule_group g
JOIN trading.td_strategy s ON g.strategy_id = s.id
WHERE s.strategy_id = 'buffett_value' AND g.group_type = 'cross_section';

INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_low_volatility', 0.2, '{}', 3
FROM trading.td_strategy_rule_group g
JOIN trading.td_strategy s ON g.strategy_id = s.id
WHERE s.strategy_id = 'buffett_value' AND g.group_type = 'cross_section';

-- ==================== 策略2: 价值动量 ====================
-- 价值+低波+动量+资金流四因子筛选，阈值0.5

INSERT INTO trading.td_strategy (strategy_id, name, description, cross_section_config, time_series_config, position_sizing_config, risk_overrides, universe_pool, status)
VALUES (
  'value_momentum', '价值动量',
  '价值+低波+动量+资金流四因子筛选',
  '{"method": "weighted_score", "threshold": 0.5}',
  '{}',
  '{"strategy": "equal_weight", "max_total_weight": 0.95}',
  '{"max_position_pct": 0.10, "max_positions": 10}',
  'idx_300', 'active'
) ON CONFLICT (strategy_id) DO NOTHING;

-- 截面规则组
INSERT INTO trading.td_strategy_rule_group (strategy_id, group_type, combination_method, combination_params, threshold)
SELECT id, 'cross_section', 'weighted_score', '{"threshold": 0.5}', 0.5
FROM trading.td_strategy WHERE strategy_id = 'value_momentum';

-- 规则绑定
INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_value_filter', 0.3, '{}', 1
FROM trading.td_strategy_rule_group g
JOIN trading.td_strategy s ON g.strategy_id = s.id
WHERE s.strategy_id = 'value_momentum' AND g.group_type = 'cross_section';

INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_low_volatility', 0.2, '{}', 2
FROM trading.td_strategy_rule_group g
JOIN trading.td_strategy s ON g.strategy_id = s.id
WHERE s.strategy_id = 'value_momentum' AND g.group_type = 'cross_section';

INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_momentum_filter', 0.3, '{}', 3
FROM trading.td_strategy_rule_group g
JOIN trading.td_strategy s ON g.strategy_id = s.id
WHERE s.strategy_id = 'value_momentum' AND g.group_type = 'cross_section';

INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_fund_flow_filter', 0.2, '{}', 4
FROM trading.td_strategy_rule_group g
JOIN trading.td_strategy s ON g.strategy_id = s.id
WHERE s.strategy_id = 'value_momentum' AND g.group_type = 'cross_section';

-- ==================== 策略3: 多因子共振 ====================
-- 动量+价值+资金流+技术面多维度共振确认，阈值0.3

INSERT INTO trading.td_strategy (strategy_id, name, description, cross_section_config, time_series_config, position_sizing_config, risk_overrides, universe_pool, status)
VALUES (
  'multi_factor_resonance', '多因子共振',
  '动量+价值+资金流+技术面多维度共振确认',
  '{"method": "weighted_score", "threshold": 0.3}',
  '{}',
  '{"strategy": "signal_weight", "max_total_weight": 0.95}',
  '{"max_position_pct": 0.08, "max_positions": 15}',
  'idx_500', 'active'
) ON CONFLICT (strategy_id) DO NOTHING;

-- 截面规则组
INSERT INTO trading.td_strategy_rule_group (strategy_id, group_type, combination_method, combination_params, threshold)
SELECT id, 'cross_section', 'weighted_score', '{"threshold": 0.3}', 0.3
FROM trading.td_strategy WHERE strategy_id = 'multi_factor_resonance';

-- 规则绑定（SPI 插件作为唯一规则）
INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_multi_factor_resonance', 1.0, '{"min_resonance_dims": 3}', 1
FROM trading.td_strategy_rule_group g
JOIN trading.td_strategy s ON g.strategy_id = s.id
WHERE s.strategy_id = 'multi_factor_resonance' AND g.group_type = 'cross_section';
