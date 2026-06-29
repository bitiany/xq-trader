-- ============================================================
-- 006: 因子系统对齐迁移 — 状态收敛 + stats 扩展
-- ============================================================
-- 背景:
--   1. 因子生命周期文档定义为 2 态（active/deprecated），但代码遗留
--      draft/testing 中间态。本次将 DB 中 draft/testing 一次性收敛为 active。
--   2. fac_factor_stats 缺少 group_returns / ic_decay_curve 持久化字段，
--      导致前端因子详情抽屉的分层收益柱状图与 IC 衰减曲线无法渲染。
--      （参考 docs/factor-product-design.md §7、§10.2 P1 项）
-- 变更内容:
--   1. research.fac_factor_registry: status draft/testing → active
--   2. research.fac_factor_stats: 新增 group_returns / ic_decay_curve JSONB 列
-- ============================================================

BEGIN;

-- ============================================================
-- 1. 因子状态收敛为 2 态（active/deprecated）
-- ============================================================
-- deprecated 保持不变（人工停用的因子不复活）
UPDATE research.fac_factor_registry
SET status = 'active'
WHERE status IN ('draft', 'testing');

COMMENT ON COLUMN research.fac_factor_registry.status IS '状态 active/deprecated（2 态生命周期）';

-- ============================================================
-- 2. fac_factor_stats 新增 group_returns / ic_decay_curve
-- ============================================================
-- group_returns: 分层回测各组年化收益 {"Q1": 0.02, "Q2": 0.05, ..., "Q5": 0.15}
-- ic_decay_curve: IC 衰减曲线 [{"h": 1, "ic": 0.05}, {"h": 2, "ic": 0.04}, ...]
ALTER TABLE research.fac_factor_stats
  ADD COLUMN IF NOT EXISTS group_returns JSONB,
  ADD COLUMN IF NOT EXISTS ic_decay_curve JSONB;

COMMENT ON COLUMN research.fac_factor_stats.group_returns IS '分层回测各组年化收益 JSONB: {"Q1":..,"Q5":..}';
COMMENT ON COLUMN research.fac_factor_stats.ic_decay_curve IS 'IC 衰减曲线 JSONB: [{"h":1,"ic":0.05},...]';

COMMIT;
