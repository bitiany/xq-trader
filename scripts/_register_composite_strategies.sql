-- 注册基于合成因子的时序策略规则与策略配置
-- 包含 3 个表达式规则 + 3 个策略

-- ===== 1. 规则注册 =====

-- 1.1 日频合成因子阈值规则（composite_alpha 是日频综合合成因子，已 Z-score 标准化）
INSERT INTO trading.td_rule_registry
    (rule_id, name, category, factors, description, is_builtin, status, definition, rule_type)
VALUES
    ('ts_composite_alpha_threshold',
     '日频合成因子阈值',
     'timing',
     '["composite_alpha"]'::jsonb,
     '基于日频综合合成因子 composite_alpha 的 Z-score 阈值: 大于 0.5 买入, 小于 -0.5 卖出',
     true,
     'active',
     '{"buy_expr": "composite_alpha > 0.5", "sell_expr": "composite_alpha < -0.5"}'::jsonb,
     'expression')
ON CONFLICT (rule_id) DO UPDATE SET
    name = EXCLUDED.name,
    factors = EXCLUDED.factors,
    description = EXCLUDED.description,
    definition = EXCLUDED.definition,
    rule_type = EXCLUDED.rule_type,
    updated_at = NOW();

-- 1.2 季频合成因子趋势规则（composite_alpha_quarterly 是季频综合合成因子，向前填充到日频）
INSERT INTO trading.td_rule_registry
    (rule_id, name, category, factors, description, is_builtin, status, definition, rule_type)
VALUES
    ('ts_quarterly_composite_trend',
     '季频合成因子趋势',
     'timing',
     '["composite_alpha_quarterly"]'::jsonb,
     '基于季频综合合成因子 composite_alpha_quarterly 的趋势: 大于 0 买入, 小于 0 卖出 (PIT 向前填充到日频)',
     true,
     'active',
     '{"buy_expr": "composite_alpha_quarterly > 0", "sell_expr": "composite_alpha_quarterly < 0"}'::jsonb,
     'expression')
ON CONFLICT (rule_id) DO UPDATE SET
    name = EXCLUDED.name,
    factors = EXCLUDED.factors,
    description = EXCLUDED.description,
    definition = EXCLUDED.definition,
    rule_type = EXCLUDED.rule_type,
    updated_at = NOW();

-- 1.3 资金面 A/B 因子规则（main_net_pct_chg 是大单净流入占比变化，A/B 级因子）
INSERT INTO trading.td_rule_registry
    (rule_id, name, category, factors, description, is_builtin, status, definition, rule_type)
VALUES
    ('ts_main_net_pct_chg',
     '主力净流入占比变化',
     'timing',
     '["main_net_pct_chg"]'::jsonb,
     '基于主力净流入占比变化的 A/B 因子信号: 大于 0 买入, 小于 0 卖出',
     true,
     'active',
     '{"buy_expr": "main_net_pct_chg > 0", "sell_expr": "main_net_pct_chg < 0"}'::jsonb,
     'expression')
ON CONFLICT (rule_id) DO UPDATE SET
    name = EXCLUDED.name,
    factors = EXCLUDED.factors,
    description = EXCLUDED.description,
    definition = EXCLUDED.definition,
    rule_type = EXCLUDED.rule_type,
    updated_at = NOW();

-- ===== 2. 策略注册 =====

-- 2.1 日频合成因子阈值策略
INSERT INTO trading.td_strategy
    (strategy_id, name, description, status, strategy_type, config)
VALUES
    ('ts_composite_alpha_threshold',
     '日频合成因子阈值策略',
     '基于日频综合合成因子 composite_alpha 的 Z-score 阈值产生买卖信号',
     'active',
     'timing',
     '{"groups": [{"name": "合成因子阈值组", "rules": [{"weight": 1.0, "rule_id": "ts_composite_alpha_threshold"}], "fusion": {"method": "or", "buy_threshold": 0.5, "sell_threshold": 0.5}, "group_id": "composite_alpha_group"}], "group_fusion": {"method": "or"}}'::jsonb)
ON CONFLICT (strategy_id) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    config = EXCLUDED.config,
    updated_at = NOW();

-- 2.2 季频合成因子趋势策略
INSERT INTO trading.td_strategy
    (strategy_id, name, description, status, strategy_type, config)
VALUES
    ('ts_quarterly_composite_trend',
     '季频合成因子趋势策略',
     '基于季频综合合成因子 composite_alpha_quarterly 的趋势产生买卖信号 (PIT 向前填充)',
     'active',
     'timing',
     '{"groups": [{"name": "季频合成因子组", "rules": [{"weight": 1.0, "rule_id": "ts_quarterly_composite_trend"}], "fusion": {"method": "or", "buy_threshold": 0.5, "sell_threshold": 0.5}, "group_id": "quarterly_composite_group"}], "group_fusion": {"method": "or"}}'::jsonb)
ON CONFLICT (strategy_id) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    config = EXCLUDED.config,
    updated_at = NOW();

-- 2.3 A/B 因子 + 合成因子组合策略（多规则组分层层融合）
INSERT INTO trading.td_strategy
    (strategy_id, name, description, status, strategy_type, config)
VALUES
    ('ts_factor_combo_ab_composite',
     'A/B因子+合成因子组合策略',
     '多因子组合策略: 日频合成因子组(权重0.5) + 资金面A/B因子组(权重0.5), 组间加权评分融合',
     'active',
     'timing',
     '{"groups": [{"name": "合成因子组", "rules": [{"weight": 1.0, "rule_id": "ts_composite_alpha_threshold"}], "fusion": {"method": "or", "buy_threshold": 0.5, "sell_threshold": 0.5}, "group_id": "composite_group"}, {"name": "资金面A/B因子组", "rules": [{"weight": 1.0, "rule_id": "ts_main_net_pct_chg"}], "fusion": {"method": "or", "buy_threshold": 0.5, "sell_threshold": 0.5}, "group_id": "ab_factor_group"}], "group_fusion": {"method": "weighted_score", "weights": {"composite_group": 0.5, "ab_factor_group": 0.5}, "buy_threshold": 0.5, "sell_threshold": 0.5}}'::jsonb)
ON CONFLICT (strategy_id) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    config = EXCLUDED.config,
    updated_at = NOW();
