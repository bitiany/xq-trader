-- ============================================================
-- 010: 修复 cs_multi_factor_resonance 规则依赖因子
-- ============================================================
-- 插件 trend_mask 依赖 barra_momentum，注册表 factors 缺失会导致零命中。
-- ============================================================

BEGIN;

UPDATE trading.td_rule_registry
SET
    factors = '["mom_20d", "barra_momentum", "hist_vol_20", "ep", "cs_main_net_pct", "rsi_14", "boll_position"]'::jsonb,
    updated_at = NOW()
WHERE rule_id = 'cs_multi_factor_resonance';

COMMIT;
