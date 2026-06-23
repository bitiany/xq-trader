-- ============================================================
-- P2 数据库迁移: 策略 + 规则表结构简化为 JSONB 单表
-- ============================================================
-- 变更内容:
--   1. td_strategy: 新增 config JSONB, 删除旧字段
--   2. td_rule_registry: 新增 definition JSONB + rule_type, 删除旧字段, 重命名 type 值
--   3. 删除 td_strategy_rule_group / td_strategy_rule_binding / td_rule_factor_dep
--   4. 新增 td_backtest_run / td_backtest_result
-- ============================================================

BEGIN;

-- ============================================================
-- 1. td_strategy
-- ============================================================
ALTER TABLE trading.td_strategy
  ADD COLUMN IF NOT EXISTS config JSONB NOT NULL DEFAULT '{}'::jsonb;

-- 迁移旧数据: 将旧字段内容合并到 config（如无可迁移内容则留空）
UPDATE trading.td_strategy
  SET config = jsonb_build_object(
    'groups', '[]'::jsonb
  )
  WHERE config = '{}'::jsonb;

-- 删除旧字段
ALTER TABLE trading.td_strategy
  DROP COLUMN IF EXISTS cross_section_config,
  DROP COLUMN IF EXISTS time_series_config,
  DROP COLUMN IF EXISTS position_sizing_config,
  DROP COLUMN IF EXISTS risk_overrides,
  DROP COLUMN IF EXISTS universe_pool;

-- 更新注释
COMMENT ON COLUMN trading.td_strategy.strategy_type IS '策略类型: selection(截面选股) / timing(时序回测)';
COMMENT ON COLUMN trading.td_strategy.config IS '策略主配置（groups + group_fusion + 类型特有配置）';


-- ============================================================
-- 2. td_rule_registry
-- ============================================================
ALTER TABLE trading.td_rule_registry
  ADD COLUMN IF NOT EXISTS definition JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS rule_type VARCHAR(16) NOT NULL DEFAULT 'expression';

-- 迁移旧数据: expression → expression, 其余 plugin
UPDATE trading.td_rule_registry
  SET rule_type = CASE WHEN "type" = 'expression' THEN 'expression' ELSE 'plugin' END,
      definition = CASE
        WHEN "type" = 'expression' THEN jsonb_build_object('expr', COALESCE(expression, ''))
        WHEN "type" = 'spi' THEN jsonb_build_object('plugin_class', COALESCE(spi_class, ''))
        ELSE '{}'::jsonb
      END;

-- 删除旧字段
ALTER TABLE trading.td_rule_registry
  DROP COLUMN IF EXISTS "type",
  DROP COLUMN IF EXISTS expression,
  DROP COLUMN IF EXISTS spi_class,
  DROP COLUMN IF EXISTS signal_mapping,
  DROP COLUMN IF EXISTS config_schema,
  DROP COLUMN IF EXISTS default_config;

COMMENT ON COLUMN trading.td_rule_registry.rule_type IS '类型: expression(表达式) / plugin(SPI 插件)';
COMMENT ON COLUMN trading.td_rule_registry.definition IS '规则定义（按 rule_type 不同：buy/sell/bullish/bearish 表达式或 plugin_class）';
COMMENT ON COLUMN trading.td_rule_registry.category IS '类别: selection(仅截面) / timing(仅时序) / both(均可)';


-- ============================================================
-- 3. 删除旧表
-- ============================================================
DROP TABLE IF EXISTS trading.td_strategy_rule_binding CASCADE;
DROP TABLE IF EXISTS trading.td_strategy_rule_group CASCADE;
DROP TABLE IF EXISTS trading.td_rule_factor_dep CASCADE;


-- ============================================================
-- 4. 新增 td_backtest_run
-- ============================================================
CREATE TABLE IF NOT EXISTS trading.td_backtest_run (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    run_id VARCHAR(64) NOT NULL UNIQUE,
    strategy_id VARCHAR(64) NOT NULL,
    symbols JSONB NOT NULL DEFAULT '[]'::jsonb,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    initial_cash NUMERIC(20, 4) NOT NULL,
    commission NUMERIC(8, 6) NOT NULL DEFAULT 0.0003,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS ix_backtest_run_strategy_id ON trading.td_backtest_run(strategy_id);
COMMENT ON TABLE trading.td_backtest_run IS '回测运行记录';
COMMENT ON COLUMN trading.td_backtest_run.run_id IS '回测运行唯一标识（UUID）';
COMMENT ON COLUMN trading.td_backtest_run.strategy_id IS '策略编码 → td_strategy.strategy_id';
COMMENT ON COLUMN trading.td_backtest_run.symbols IS '回测标的列表（运行时入参，与策略配置解耦）';
COMMENT ON COLUMN trading.td_backtest_run.initial_cash IS '初始资金';
COMMENT ON COLUMN trading.td_backtest_run.commission IS '手续费率';
COMMENT ON COLUMN trading.td_backtest_run.status IS '状态: pending/running/success/failed';


-- ============================================================
-- 5. 新增 td_backtest_result
-- ============================================================
CREATE TABLE IF NOT EXISTS trading.td_backtest_result (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now(),
    run_id VARCHAR(64) NOT NULL UNIQUE,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    equity_curve JSONB NOT NULL DEFAULT '[]'::jsonb,
    trades JSONB NOT NULL DEFAULT '[]'::jsonb
);
COMMENT ON TABLE trading.td_backtest_result IS '回测绩效结果';
COMMENT ON COLUMN trading.td_backtest_result.run_id IS '回测运行 ID → td_backtest_run.run_id';
COMMENT ON COLUMN trading.td_backtest_result.metrics IS '绩效指标（total_return/sharpe/max_drawdown/win_rate 等）';
COMMENT ON COLUMN trading.td_backtest_result.equity_curve IS '权益曲线（每日净值快照列表）';
COMMENT ON COLUMN trading.td_backtest_result.trades IS '交易记录（含信号触发依据和因子值）';

COMMIT;