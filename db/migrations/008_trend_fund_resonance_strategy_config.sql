-- ============================================================
-- 008: 补全 trend_fund_resonance 策略 config
-- ============================================================
-- 趋势资金共振：强动量 + 主力净流入 + RSI 不超买，AND 融合
-- ============================================================

BEGIN;

UPDATE trading.td_strategy
SET
    config = '{
      "top_n": 50,
      "exclude_short": true,
      "groups": [
        {
          "group_id": "trend_fund_resonance",
          "name": "趋势资金共振规则组",
          "rules": [
            {"rule_id": "cs_strong_momentum", "weight": 1.0},
            {"rule_id": "cs_fund_flow_filter", "weight": 1.0},
            {"rule_id": "cs_rsi_range", "weight": 1.0}
          ],
          "fusion": {
            "method": "and",
            "buy_threshold": 0.5,
            "sell_threshold": 0.5
          }
        }
      ]
    }'::jsonb,
    updated_at = NOW()
WHERE strategy_id = 'trend_fund_resonance';

COMMIT;
