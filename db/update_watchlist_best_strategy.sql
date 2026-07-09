-- 更新自选池 signal_config 为每标的最优策略
-- 基于上一轮回测结果：6/1~7/8 期间每标的的最佳策略

BEGIN;

-- 002463.SZ -> ts_chanlun_signal (149.68%)
UPDATE trading.td_watchlist_item
SET signal_config = jsonb_set(signal_config, '{strategy_id}', '"ts_chanlun_signal"', false)
WHERE symbol = '002463.SZ';

-- 002938.SZ -> ts_fund5d_macd (83.10%)
UPDATE trading.td_watchlist_item
SET signal_config = jsonb_set(signal_config, '{strategy_id}', '"ts_fund5d_macd"', false)
WHERE symbol = '002938.SZ';

-- 300136.SZ -> ts_fusion_cfg4_chan_0.40 (158.99%)
UPDATE trading.td_watchlist_item
SET signal_config = jsonb_set(signal_config, '{strategy_id}', '"ts_fusion_cfg4_chan_0.40"', false)
WHERE symbol = '300136.SZ';

-- 300433.SZ -> ts_fusion_cfg4_chan_0.40 (94.83%)
UPDATE trading.td_watchlist_item
SET signal_config = jsonb_set(signal_config, '{strategy_id}', '"ts_fusion_cfg4_chan_0.40"', false)
WHERE symbol = '300433.SZ';

-- 600188.SH -> ts_chanlun_signal (47.84%)
UPDATE trading.td_watchlist_item
SET signal_config = jsonb_set(signal_config, '{strategy_id}', '"ts_chanlun_signal"', false)
WHERE symbol = '600188.SH';

-- 600206.SH -> ts_chanlun_signal (112.57%)
UPDATE trading.td_watchlist_item
SET signal_config = jsonb_set(signal_config, '{strategy_id}', '"ts_chanlun_signal"', false)
WHERE symbol = '600206.SH';

-- 600522.SH -> ts_chanlun_signal (130.26%)
UPDATE trading.td_watchlist_item
SET signal_config = jsonb_set(signal_config, '{strategy_id}', '"ts_chanlun_signal"', false)
WHERE symbol = '600522.SH';

-- 600580.SH -> ts_chanlun_signal (124.57%)
UPDATE trading.td_watchlist_item
SET signal_config = jsonb_set(signal_config, '{strategy_id}', '"ts_chanlun_signal"', false)
WHERE symbol = '600580.SH';

-- 601138.SH -> ts_chanlun_signal (130.43%)
UPDATE trading.td_watchlist_item
SET signal_config = jsonb_set(signal_config, '{strategy_id}', '"ts_chanlun_signal"', false)
WHERE symbol = '601138.SH';

-- 601958.SH -> ts_chanlun_signal (105.63%)
UPDATE trading.td_watchlist_item
SET signal_config = jsonb_set(signal_config, '{strategy_id}', '"ts_chanlun_signal"', false)
WHERE symbol = '601958.SH';

COMMIT;
