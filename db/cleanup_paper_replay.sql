-- 清理 trading schema 中 2026-06-01 至 2026-07-08 的模拟盘回放数据
-- 执行前确认：账户 1 的历史信号/预订单/订单/成交/快照全部清理
-- 重置账户资金为 100 万

BEGIN;

-- 1. 先删子表：订单事件（通过 order_id 关联）
DELETE FROM trading.td_order_event
WHERE order_id IN (
    SELECT id FROM trading.td_order
    WHERE signal_date BETWEEN '2026-06-01' AND '2026-07-08'
       OR execution_date BETWEEN '2026-06-01' AND '2026-07-08'
);

-- 2. 删成交记录
DELETE FROM trading.td_trade
WHERE trade_time BETWEEN '2026-06-01' AND '2026-07-09';

-- 3. 删订单
DELETE FROM trading.td_order
WHERE signal_date BETWEEN '2026-06-01' AND '2026-07-08'
   OR execution_date BETWEEN '2026-06-01' AND '2026-07-08';

-- 4. 删预订单
DELETE FROM trading.td_pre_order
WHERE signal_date BETWEEN '2026-06-01' AND '2026-07-08';

-- 5. 删配仓结果
DELETE FROM trading.td_position_sizing_result
WHERE signal_date BETWEEN '2026-06-01' AND '2026-07-08';

-- 6. 删信号融合结果
DELETE FROM trading.td_signal_fusion_result
WHERE signal_date BETWEEN '2026-06-01' AND '2026-07-08';

-- 7. 删原始信号
DELETE FROM trading.td_trading_signal
WHERE signal_date BETWEEN '2026-06-01' AND '2026-07-08';

-- 8. 删持仓快照
DELETE FROM trading.td_position_snapshot
WHERE snapshot_date BETWEEN '2026-06-01' AND '2026-07-08';

-- 9. 删账户快照
DELETE FROM trading.td_account_snapshot
WHERE snapshot_date BETWEEN '2026-06-01' AND '2026-07-08';

-- 10. 重置账户 1 的可用现金为初始资金 1,000,000
UPDATE trading.td_account
SET available_cash = 1000000.0000,
    frozen_cash = 0.0000
WHERE id = 1;

COMMIT;
