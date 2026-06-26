-- ============================================================
-- 005: td_order_event / td_trade 补充 created_at 字段
-- ============================================================
-- 背景: OrderEvent / Trade 继承 Base（append-only 事件表），缺少
--       created_at 时间戳，无法按入库时间排序与追溯。
-- 变更内容:
--   1. td_order_event 新增 created_at 列（NOT NULL，默认 now()）
--   2. td_trade 新增 created_at 列（NOT NULL，默认 now()）
-- ============================================================

BEGIN;

-- ============================================================
-- 1. td_order_event 新增 created_at
-- ============================================================
ALTER TABLE trading.td_order_event
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();

COMMENT ON COLUMN trading.td_order_event.created_at IS '事件入库时间';

-- ============================================================
-- 2. td_trade 新增 created_at
-- ============================================================
ALTER TABLE trading.td_trade
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();

COMMENT ON COLUMN trading.td_trade.created_at IS '成交记录入库时间';

COMMIT;
