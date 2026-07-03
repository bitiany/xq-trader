-- ============================================================
-- 009: 补全全部成熟截面选股策略 config
-- ============================================================
-- 保留 8 套业界主流策略模板，按 description 绑定规则组与融合方式。
-- 无 test_* 类选股策略需删除（timing 测试策略在 003 中已清理）。
-- ============================================================

BEGIN;

-- 1. 巴菲特价值投资：价值 + 质量 + 低波（Fama-French 价值/质量因子）
UPDATE trading.td_strategy
SET config = '{
  "top_n": 50,
  "exclude_short": true,
  "groups": [{
    "group_id": "value_quality_lowvol",
    "name": "巴菲特价值投资规则组",
    "rules": [
      {"rule_id": "cs_value_filter", "weight": 0.35},
      {"rule_id": "cs_quality_filter", "weight": 0.35},
      {"rule_id": "cs_low_volatility", "weight": 0.30}
    ],
    "fusion": {
      "method": "weighted_score",
      "weights": {
        "cs_value_filter": 0.35,
        "cs_quality_filter": 0.35,
        "cs_low_volatility": 0.30
      },
      "buy_threshold": 0.6,
      "sell_threshold": 0.5
    }
  }]
}'::jsonb, updated_at = NOW()
WHERE strategy_id = 'buffett_value';

-- 2. 格雷厄姆深度价值：极低估值 + 财务安全 + 低杠杆（Graham 烟蒂股）
UPDATE trading.td_strategy
SET config = '{
  "top_n": 50,
  "exclude_short": true,
  "groups": [{
    "group_id": "graham_deep",
    "name": "格雷厄姆深度价值规则组",
    "rules": [
      {"rule_id": "cs_deep_value", "weight": 1.0},
      {"rule_id": "cs_financial_safety", "weight": 1.0},
      {"rule_id": "cs_low_leverage", "weight": 1.0}
    ],
    "fusion": {"method": "and", "buy_threshold": 0.5, "sell_threshold": 0.5}
  }]
}'::jsonb, updated_at = NOW()
WHERE strategy_id = 'graham_deep_value';

-- 3. 高股息红利：股息率 + 合理估值 + 财务安全
UPDATE trading.td_strategy
SET config = '{
  "top_n": 50,
  "exclude_short": true,
  "groups": [{
    "group_id": "dividend_value_safety",
    "name": "高股息红利规则组",
    "rules": [
      {"rule_id": "cs_high_dividend", "weight": 1.0},
      {"rule_id": "cs_value_filter", "weight": 1.0},
      {"rule_id": "cs_financial_safety", "weight": 1.0}
    ],
    "fusion": {"method": "and", "buy_threshold": 0.5, "sell_threshold": 0.5}
  }]
}'::jsonb, updated_at = NOW()
WHERE strategy_id = 'high_dividend';

-- 4. 低波动龙头：低波 + 质量 + RSI 区间（低波 anomaly + 质量因子）
UPDATE trading.td_strategy
SET config = '{
  "top_n": 50,
  "exclude_short": true,
  "groups": [{
    "group_id": "lowvol_quality",
    "name": "低波动龙头规则组",
    "rules": [
      {"rule_id": "cs_low_volatility", "weight": 1.0},
      {"rule_id": "cs_quality_filter", "weight": 1.0},
      {"rule_id": "cs_rsi_range", "weight": 1.0}
    ],
    "fusion": {"method": "and", "buy_threshold": 0.5, "sell_threshold": 0.5}
  }]
}'::jsonb, updated_at = NOW()
WHERE strategy_id = 'low_vol_leader';

-- 5. 多因子共振：SPI 插件（AQR 多因子 + 华泰金工共振框架）
UPDATE trading.td_strategy
SET config = '{
  "top_n": 50,
  "exclude_short": true,
  "groups": [{
    "group_id": "multi_factor",
    "name": "多因子共振规则组",
    "rules": [
      {"rule_id": "cs_multi_factor_resonance", "weight": 1.0}
    ],
    "fusion": {"method": "or", "buy_threshold": 0.5, "sell_threshold": 0.5}
  }]
}'::jsonb, updated_at = NOW()
WHERE strategy_id = 'multi_factor_resonance';

-- 6. 价值动量：价值 + 低波 + 动量 + 资金流（四因子合成）
UPDATE trading.td_strategy
SET config = '{
  "top_n": 50,
  "exclude_short": true,
  "groups": [{
    "group_id": "value_momentum_flow",
    "name": "价值动量规则组",
    "rules": [
      {"rule_id": "cs_value_filter", "weight": 0.25},
      {"rule_id": "cs_low_volatility", "weight": 0.25},
      {"rule_id": "cs_momentum_filter", "weight": 0.25},
      {"rule_id": "cs_fund_flow_filter", "weight": 0.25}
    ],
    "fusion": {
      "method": "weighted_score",
      "weights": {
        "cs_value_filter": 0.25,
        "cs_low_volatility": 0.25,
        "cs_momentum_filter": 0.25,
        "cs_fund_flow_filter": 0.25
      },
      "buy_threshold": 0.5,
      "sell_threshold": 0.5
    }
  }]
}'::jsonb, updated_at = NOW()
WHERE strategy_id = 'value_momentum';

-- peter_lynch_growth / trend_fund_resonance 已在 008 或此前配置，此处不重复更新

COMMIT;
