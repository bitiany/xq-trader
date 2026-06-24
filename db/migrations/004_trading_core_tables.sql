-- ============================================================
-- 004: Trading 核心表补充 — 缺失列 + 种子数据
-- ============================================================
-- 前置: 001_init.sql 已创建核心表结构
-- 变更内容:
--   1. 补充 td_order 缺失列 (account_id, platform_order_id)
--   2. 补充 td_trade 缺失列 (account_id)
--   3. 插入种子数据: 2 个交易账户 + 8 条内置风控规则
-- ============================================================

BEGIN;

-- ============================================================
-- 1. td_order 补充列
-- ============================================================
ALTER TABLE trading.td_order
  ADD COLUMN IF NOT EXISTS account_id INTEGER,
  ADD COLUMN IF NOT EXISTS platform_order_id UUID UNIQUE DEFAULT gen_random_uuid();

CREATE INDEX IF NOT EXISTS ix_td_order_account_id ON trading.td_order (account_id);

COMMENT ON COLUMN trading.td_order.account_id IS '账户ID';
COMMENT ON COLUMN trading.td_order.platform_order_id IS '平台内部订单ID';

-- ============================================================
-- 2. td_trade 补充列
-- ============================================================
ALTER TABLE trading.td_trade
  ADD COLUMN IF NOT EXISTS account_id INTEGER;

CREATE INDEX IF NOT EXISTS ix_td_trade_account_id ON trading.td_trade (account_id);

COMMENT ON COLUMN trading.td_trade.account_id IS '账户ID';

-- ============================================================
-- 3. 种子数据 — 交易账户
-- ============================================================
INSERT INTO trading.td_account (account_code, account_name, account_type, broker_type, initial_capital, available_cash, frozen_cash, reduce_only, is_enabled, description)
VALUES
  ('live-001', '实盘账户-001', 'live', 'qmt', 1000000, 1000000, 0, false, true, '默认实盘账户'),
  ('paper-001', '模拟账户-001', 'paper', 'simulated', 1000000, 1000000, 0, false, true, '默认模拟账户')
ON CONFLICT (account_code) DO NOTHING;

-- ============================================================
-- 4. 种子数据 — 内置风控规则
-- ============================================================
INSERT INTO trading.td_risk_rule (rule_code, name, category, level, is_enabled, params, scope, description) VALUES ('trading_session', '交易时段检查', 'timing', 'info', true, '{"start":"09:30","morning_end":"11:30","afternoon_start":"13:00","end":"15:00"}', 'global', '仅在交易时段内允许下单') ON CONFLICT (rule_code) DO NOTHING;
INSERT INTO trading.td_risk_rule (rule_code, name, category, level, is_enabled, params, scope, description) VALUES ('daily_loss_circuit', '日亏损熔断', 'circuit_breaker', 'critical', true, '{"threshold":-0.02}', 'global', '当日亏损超过阈值时熔断，禁止新开仓') ON CONFLICT (rule_code) DO NOTHING;
INSERT INTO trading.td_risk_rule (rule_code, name, category, level, is_enabled, params, scope, description) VALUES ('max_position_pct', '单票仓位上限', 'position', 'warn', true, CAST('{"max_pct":0.1}' AS JSONB), 'global', '单票持仓占比不超过10%') ON CONFLICT (rule_code) DO NOTHING;
INSERT INTO trading.td_risk_rule (rule_code, name, category, level, is_enabled, params, scope, description) VALUES ('max_positions', '持仓数量上限', 'position', 'warn', true, CAST('{"max_count":10}' AS JSONB), 'global', '同时持仓标的数不超过10') ON CONFLICT (rule_code) DO NOTHING;
INSERT INTO trading.td_risk_rule (rule_code, name, category, level, is_enabled, params, scope, description) VALUES ('max_order_amount', '单笔金额上限', 'capital', 'warn', true, CAST('{"max_amount":500000}' AS JSONB), 'global', '单笔委托金额不超过50万') ON CONFLICT (rule_code) DO NOTHING;
INSERT INTO trading.td_risk_rule (rule_code, name, category, level, is_enabled, params, scope, description) VALUES ('t_plus_1_sell', 'T+1卖出限制', 'capital', 'info', true, CAST('{"check":"available_qty"}' AS JSONB), 'global', '卖出数量不超过可用数量(T+1)') ON CONFLICT (rule_code) DO NOTHING;
INSERT INTO trading.td_risk_rule (rule_code, name, category, level, is_enabled, params, scope, description) VALUES ('cash_sufficient', '现金充足检查', 'capital', 'info', true, CAST('{"check":"cash>=buy_amount"}' AS JSONB), 'global', '买入前检查可用现金是否充足') ON CONFLICT (rule_code) DO NOTHING;
INSERT INTO trading.td_risk_rule (rule_code, name, category, level, is_enabled, params, scope, description) VALUES ('signal_ttl', '信号有效期', 'timing', 'info', true, CAST('{"ttl_seconds":300}' AS JSONB), 'global', '信号超过有效期不执行') ON CONFLICT (rule_code) DO NOTHING;

COMMIT;
