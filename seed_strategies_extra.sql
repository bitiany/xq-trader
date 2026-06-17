-- ============================================================
-- 业界著名选股策略种子数据扩展（独立脚本，可重复执行）
-- 因子来源（参考 docs/factor-architecture.md, docs/factor-catalog.md）：
--   stock.fac_factor_value      — mom_20d / hist_vol_20 / rsi_14 / boll_position / cs_main_net_pct
--   stock.sdc_daily_indicator   — pe_ttm / pb / dv_ratio (衍生 ep / bp)
--   stock.sdc_financial_indicator — roe / grossprofit_margin / current_ratio / quick_ratio / debt_to_assets
-- ============================================================

-- ==================== 新增规则注册表 ====================
INSERT INTO trading.td_rule_registry (rule_id, name, category, type, expression, factors, signal_mapping, default_config, description, is_builtin, status) VALUES
('cs_high_dividend', '高股息过滤', 'cross_section', 'expression', 'dv_ratio > 3', '["dv_ratio"]', '{"true": {"direction": "long", "confidence": 0.6}, "false": {"direction": "neutral", "confidence": 0.0}}', '{}', '股息率(TTM) > 3%', true, 'active'),
('cs_financial_safety', '财务安全过滤', 'cross_section', 'expression', 'current_ratio > 1.5 and quick_ratio > 1.0', '["current_ratio", "quick_ratio"]', '{"true": {"direction": "long", "confidence": 0.6}, "false": {"direction": "neutral", "confidence": 0.0}}', '{}', '流动比率>1.5 且 速动比率>1.0', true, 'active'),
('cs_low_leverage', '低杠杆过滤', 'cross_section', 'expression', 'debt_to_assets < 50', '["debt_to_assets"]', '{"true": {"direction": "long", "confidence": 0.5}, "false": {"direction": "neutral", "confidence": 0.0}}', '{}', '资产负债率 < 50%', true, 'active'),
('cs_deep_value', '深度价值(Graham)', 'cross_section', 'expression', 'pe_ttm > 0 and pe_ttm < 15 and pb > 0 and pb < 1.5', '["pe_ttm", "pb"]', '{"true": {"direction": "long", "confidence": 0.7}, "false": {"direction": "neutral", "confidence": 0.0}}', '{}', 'Graham 价值乘数: PE<15 且 PB<1.5', true, 'active'),
('cs_strong_momentum', '强动量过滤', 'cross_section', 'expression', 'mom_20d > 0.05', '["mom_20d"]', '{"true": {"direction": "long", "confidence": 0.6}, "false": {"direction": "neutral", "confidence": 0.0}}', '{}', '20日动量 > 5%', true, 'active'),
('cs_rsi_range', '不超买过滤', 'cross_section', 'expression', 'rsi_14 > 30 and rsi_14 < 70', '["rsi_14"]', '{"true": {"direction": "long", "confidence": 0.4}, "false": {"direction": "neutral", "confidence": 0.0}}', '{}', 'RSI(14) 处于 30-70 中性区间', true, 'active'),
('cs_high_growth_roe', '高成长ROE过滤', 'cross_section', 'expression', 'roe > 20', '["roe"]', '{"true": {"direction": "long", "confidence": 0.7}, "false": {"direction": "neutral", "confidence": 0.0}}', '{}', '净资产收益率 > 20%（巴菲特/林奇优秀公司线）', true, 'active')
ON CONFLICT (rule_id) DO NOTHING;

-- ==================== 新增规则-因子依赖 ====================
INSERT INTO trading.td_rule_factor_dep (rule_id, factor_id, usage) VALUES
  ('cs_high_dividend', 'dv_ratio', '股息维度'),
  ('cs_financial_safety', 'current_ratio', '偿债维度'),
  ('cs_financial_safety', 'quick_ratio', '偿债维度'),
  ('cs_low_leverage', 'debt_to_assets', '杠杆维度'),
  ('cs_deep_value', 'pe_ttm', '估值维度'),
  ('cs_deep_value', 'pb', '估值维度'),
  ('cs_strong_momentum', 'mom_20d', '动量维度'),
  ('cs_rsi_range', 'rsi_14', '技术面维度'),
  ('cs_high_growth_roe', 'roe', '盈利维度')
ON CONFLICT DO NOTHING;

-- ==================== 5 个业界著名策略 ====================
INSERT INTO trading.td_strategy (strategy_id, name, description, cross_section_config, time_series_config, position_sizing_config, risk_overrides, universe_pool, status) VALUES
('graham_deep_value', '格雷厄姆深度价值', '本杰明·格雷厄姆经典烟蒂股选股法：极低估值（PE<15 且 PB<1.5）+ 财务安全（流动比率>1.5、速动比率>1.0）+ 低杠杆（资产负债率<50%）', '{"method": "weighted_score", "threshold": 0.6}', '{}', '{"strategy": "equal_weight", "max_total_weight": 0.95}', '{"max_position_pct": 0.10, "max_positions": 10}', 'all', 'active'),
('high_dividend', '高股息红利', '红利策略：高股息率（>3%）+ 合理估值（PE<25）+ 财务安全（流动比率>1.5），追求稳定现金流回报，对标中证红利策略', '{"method": "weighted_score", "threshold": 0.5}', '{}', '{"strategy": "equal_weight", "max_total_weight": 0.95}', '{"max_position_pct": 0.10, "max_positions": 15}', 'idx_300', 'active'),
('peter_lynch_growth', '林奇成长(GARP)', '彼得·林奇 GARP（Growth At Reasonable Price）策略：高 ROE（>20%）+ 合理估值（PE<25）+ 强动量（>5%）+ 良好质量（毛利率>30%）', '{"method": "weighted_score", "threshold": 0.5}', '{}', '{"strategy": "equal_weight", "max_total_weight": 0.95}', '{"max_position_pct": 0.10, "max_positions": 12}', 'idx_500', 'active'),
('low_vol_leader', '低波动龙头', '低波动 + 优质龙头筛选（沪深300成分）：低波动（年化<35%）+ 优质龙头（ROE>12%、毛利率>30%）+ 不超买（RSI 30-70）', '{"method": "weighted_score", "threshold": 0.5}', '{}', '{"strategy": "equal_weight", "max_total_weight": 0.95}', '{"max_position_pct": 0.10, "max_positions": 10}', 'idx_300', 'active'),
('trend_fund_resonance', '趋势资金共振', '动量趋势 + 主力资金共振：强动量（>5%）+ 主力净流入为正 + 不超买（RSI<70）。适合中证1000捕捉中小盘趋势', '{"method": "weighted_score", "threshold": 0.5}', '{}', '{"strategy": "signal_weight", "max_total_weight": 0.95}', '{"max_position_pct": 0.05, "max_positions": 20}', 'idx_1000', 'active')
ON CONFLICT (strategy_id) DO NOTHING;

-- ==================== 清理旧规则组与绑定（5 个策略） ====================
DELETE FROM trading.td_strategy_rule_binding WHERE group_id IN (
  SELECT g.id FROM trading.td_strategy_rule_group g
  JOIN trading.td_strategy s ON g.strategy_id = s.id
  WHERE s.strategy_id IN ('graham_deep_value', 'high_dividend', 'peter_lynch_growth', 'low_vol_leader', 'trend_fund_resonance')
);
DELETE FROM trading.td_strategy_rule_group WHERE strategy_id IN (
  SELECT id FROM trading.td_strategy WHERE strategy_id IN ('graham_deep_value', 'high_dividend', 'peter_lynch_growth', 'low_vol_leader', 'trend_fund_resonance')
);

-- ==================== 创建规则组（每个策略 1 个 cross_section 组） ====================
INSERT INTO trading.td_strategy_rule_group (strategy_id, group_type, combination_method, combination_params, threshold)
SELECT id, 'cross_section', 'weighted_score', '{"threshold": 0.6}', 0.6 FROM trading.td_strategy WHERE strategy_id = 'graham_deep_value';
INSERT INTO trading.td_strategy_rule_group (strategy_id, group_type, combination_method, combination_params, threshold)
SELECT id, 'cross_section', 'weighted_score', '{"threshold": 0.5}', 0.5 FROM trading.td_strategy WHERE strategy_id = 'high_dividend';
INSERT INTO trading.td_strategy_rule_group (strategy_id, group_type, combination_method, combination_params, threshold)
SELECT id, 'cross_section', 'weighted_score', '{"threshold": 0.5}', 0.5 FROM trading.td_strategy WHERE strategy_id = 'peter_lynch_growth';
INSERT INTO trading.td_strategy_rule_group (strategy_id, group_type, combination_method, combination_params, threshold)
SELECT id, 'cross_section', 'weighted_score', '{"threshold": 0.5}', 0.5 FROM trading.td_strategy WHERE strategy_id = 'low_vol_leader';
INSERT INTO trading.td_strategy_rule_group (strategy_id, group_type, combination_method, combination_params, threshold)
SELECT id, 'cross_section', 'weighted_score', '{"threshold": 0.5}', 0.5 FROM trading.td_strategy WHERE strategy_id = 'trend_fund_resonance';

-- ==================== 规则绑定（每个策略） ====================
-- graham_deep_value
INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_deep_value', 0.5, '{}', 1 FROM trading.td_strategy_rule_group g JOIN trading.td_strategy s ON g.strategy_id = s.id WHERE s.strategy_id = 'graham_deep_value';
INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_financial_safety', 0.3, '{}', 2 FROM trading.td_strategy_rule_group g JOIN trading.td_strategy s ON g.strategy_id = s.id WHERE s.strategy_id = 'graham_deep_value';
INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_low_leverage', 0.2, '{}', 3 FROM trading.td_strategy_rule_group g JOIN trading.td_strategy s ON g.strategy_id = s.id WHERE s.strategy_id = 'graham_deep_value';

-- high_dividend
INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_high_dividend', 0.5, '{}', 1 FROM trading.td_strategy_rule_group g JOIN trading.td_strategy s ON g.strategy_id = s.id WHERE s.strategy_id = 'high_dividend';
INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_value_filter', 0.3, '{}', 2 FROM trading.td_strategy_rule_group g JOIN trading.td_strategy s ON g.strategy_id = s.id WHERE s.strategy_id = 'high_dividend';
INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_financial_safety', 0.2, '{}', 3 FROM trading.td_strategy_rule_group g JOIN trading.td_strategy s ON g.strategy_id = s.id WHERE s.strategy_id = 'high_dividend';

-- peter_lynch_growth
INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_high_growth_roe', 0.4, '{}', 1 FROM trading.td_strategy_rule_group g JOIN trading.td_strategy s ON g.strategy_id = s.id WHERE s.strategy_id = 'peter_lynch_growth';
INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_value_filter', 0.2, '{}', 2 FROM trading.td_strategy_rule_group g JOIN trading.td_strategy s ON g.strategy_id = s.id WHERE s.strategy_id = 'peter_lynch_growth';
INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_strong_momentum', 0.2, '{}', 3 FROM trading.td_strategy_rule_group g JOIN trading.td_strategy s ON g.strategy_id = s.id WHERE s.strategy_id = 'peter_lynch_growth';
INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_quality_filter', 0.2, '{}', 4 FROM trading.td_strategy_rule_group g JOIN trading.td_strategy s ON g.strategy_id = s.id WHERE s.strategy_id = 'peter_lynch_growth';

-- low_vol_leader
INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_low_volatility', 0.4, '{}', 1 FROM trading.td_strategy_rule_group g JOIN trading.td_strategy s ON g.strategy_id = s.id WHERE s.strategy_id = 'low_vol_leader';
INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_quality_filter', 0.4, '{}', 2 FROM trading.td_strategy_rule_group g JOIN trading.td_strategy s ON g.strategy_id = s.id WHERE s.strategy_id = 'low_vol_leader';
INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_rsi_range', 0.2, '{}', 3 FROM trading.td_strategy_rule_group g JOIN trading.td_strategy s ON g.strategy_id = s.id WHERE s.strategy_id = 'low_vol_leader';

-- trend_fund_resonance
INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_strong_momentum', 0.4, '{}', 1 FROM trading.td_strategy_rule_group g JOIN trading.td_strategy s ON g.strategy_id = s.id WHERE s.strategy_id = 'trend_fund_resonance';
INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_fund_flow_filter', 0.4, '{}', 2 FROM trading.td_strategy_rule_group g JOIN trading.td_strategy s ON g.strategy_id = s.id WHERE s.strategy_id = 'trend_fund_resonance';
INSERT INTO trading.td_strategy_rule_binding (group_id, rule_id, weight, config_override, sort_order)
SELECT g.id, 'cs_rsi_range', 0.2, '{}', 3 FROM trading.td_strategy_rule_group g JOIN trading.td_strategy s ON g.strategy_id = s.id WHERE s.strategy_id = 'trend_fund_resonance';
