-- ============================================================
-- 013: 策略择时历史表 — 记录每次 strategy-timing 信号与后续走势比对
-- ============================================================
-- 用途:
--   1. 记录每次 strategy-timing 的 signal/confidence/decision
--   2. 后续走势比对回填 actual_return/verdict
--   3. 按 rule_id 聚合计算策略胜率，反哺聚合权重（样本≥30 启用）
-- ============================================================

BEGIN;

CREATE TABLE IF NOT EXISTS trading.td_strategy_timing_history (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              VARCHAR(20)   NOT NULL,
    as_of               DATE          NOT NULL,
    market_regime       VARCHAR(32),
    signals             JSONB         NOT NULL DEFAULT '[]'::jsonb,
    aggregated_signal   VARCHAR(16)   NOT NULL,
    confidence          NUMERIC(4,3)  NOT NULL,
    decision_rationale  TEXT,
    actual_return       NUMERIC(8,4),
    verdict             VARCHAR(16),
    compared_at         DATE,
    compare_window_days INTEGER,
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_td_strategy_timing_history_symbol
    ON trading.td_strategy_timing_history (symbol);

CREATE INDEX IF NOT EXISTS ix_td_strategy_timing_history_as_of
    ON trading.td_strategy_timing_history (as_of);

CREATE INDEX IF NOT EXISTS ix_td_strategy_timing_history_verdict
    ON trading.td_strategy_timing_history (verdict)
    WHERE verdict IS NOT NULL;

COMMENT ON TABLE trading.td_strategy_timing_history IS '策略择时历史 — 记录信号与后续走势比对';
COMMENT ON COLUMN trading.td_strategy_timing_history.signals IS '各策略信号列表 [{rule_id, signal, confidence, weight, key_reason}]';
COMMENT ON COLUMN trading.td_strategy_timing_history.aggregated_signal IS '综合聚合信号: buy/hold/sell';
COMMENT ON COLUMN trading.td_strategy_timing_history.confidence IS '综合置信度 0.000-1.000';
COMMENT ON COLUMN trading.td_strategy_timing_history.actual_return IS '比对窗口内实际收益率%（回填）';
COMMENT ON COLUMN trading.td_strategy_timing_history.verdict IS '走势判定: win/loss/neutral（回填，与 aggregated_signal 比对）';

COMMIT;
