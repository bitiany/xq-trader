-- ============================================================
-- 012: 个股诊股评分快照表 — stock schema
-- ============================================================
-- 用途: 存储每日五维诊股评分，支持本期/上期对比与得分走势

BEGIN;

CREATE TABLE IF NOT EXISTS stock.sdc_stock_diagnosis_snapshot (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              VARCHAR(20)  NOT NULL,
    as_of               DATE         NOT NULL,
    overall_score       DOUBLE PRECISION,
    earnings_score      DOUBLE PRECISION,
    momentum_score      DOUBLE PRECISION,
    fundamental_score   DOUBLE PRECISION,
    valuation_score     DOUBLE PRECISION,
    risk_score          DOUBLE PRECISION,
    detail              JSONB,
    summary             JSONB,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_sdc_stock_diagnosis_snapshot_symbol_as_of UNIQUE (symbol, as_of)
);

COMMENT ON TABLE  stock.sdc_stock_diagnosis_snapshot IS '个股诊股评分快照 — 五维雷达与综合得分';
COMMENT ON COLUMN stock.sdc_stock_diagnosis_snapshot.as_of IS '评分基准日（交易日）';
COMMENT ON COLUMN stock.sdc_stock_diagnosis_snapshot.detail IS '子分明细与关键指标 JSONB';
COMMENT ON COLUMN stock.sdc_stock_diagnosis_snapshot.summary IS '变化解读 bullets JSONB';

CREATE INDEX IF NOT EXISTS idx_sdc_stock_diagnosis_snapshot_symbol
    ON stock.sdc_stock_diagnosis_snapshot (symbol);
CREATE INDEX IF NOT EXISTS idx_sdc_stock_diagnosis_snapshot_as_of
    ON stock.sdc_stock_diagnosis_snapshot (as_of);

COMMIT;
