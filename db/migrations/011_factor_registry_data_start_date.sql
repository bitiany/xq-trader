-- 011_factor_registry_data_start_date.sql
-- 为因子注册表新增 data_start_date 字段，支持按因子级数据起始日期管控。
-- 背景：moneyflow_dc 数据源自 2023-09-11 起，资金流向因子须从该日期开始计算/评估/合成，
--      避免在 5 年默认窗口中因覆盖率不足 80% 被门禁拦截。

ALTER TABLE research.fac_factor_registry
    ADD COLUMN IF NOT EXISTS data_start_date DATE DEFAULT NULL;

COMMENT ON COLUMN research.fac_factor_registry.data_start_date IS
    '数据起始日期（受数据源限制，如 fund_flow 自 2023-09-11 起；NULL 表示无限制）';

-- 资金流向因子（含派生/合成）统一设为 2023-09-11
UPDATE research.fac_factor_registry
SET data_start_date = DATE '2023-09-11'
WHERE factor_id IN (
    'cs_main_net_pct', 'cs_net_mf_pct', 'huge_net_pct', 'big_net_pct',
    'z_main_net_pct', 'composite_fund_flow'
);
