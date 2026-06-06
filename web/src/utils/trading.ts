/**
 * 交易相关常量与工具函数
 */

export const SIDE_KEYS: Record<string, string> = {
  buy: 'orders.sideBuy',
  sell: 'orders.sideSell',
}

export const STATUS_KEYS: Record<string, string> = {
  pending: 'orders.statusPending',
  reported: 'orders.statusReported',
  cancelling: 'orders.statusCancelling',
  filled: 'orders.statusFilled',
  partial_filled: 'orders.statusPartialFilled',
  cancelled: 'orders.statusCancelled',
  rejected: 'orders.statusRejected',
  unknown: 'orders.statusUnknown',
}

export const ORDER_TYPE_KEYS: Record<string, string> = {
  market: 'orders.orderTypeMarket',
  limit: 'orders.orderTypeLimit',
}

export const STATUS_COLOR: Record<string, string> = {
  pending: 'processing',
  reported: 'processing',
  cancelling: 'warning',
  filled: 'success',
  partial_filled: 'warning',
  cancelled: 'default',
  rejected: 'error',
  unknown: 'default',
}

/** A股配色：红买绿卖 */
export const SIDE_ROW_CLASS: Record<string, string> = {
  buy: 'order-row--buy',
  sell: 'order-row--sell',
}

/** 信号方向 — 结合持仓判断 */
export const SIGNAL_SIDE_KEYS: Record<string, string> = {
  open: 'trading.signals.sideOpen',
  add: 'trading.signals.sideAdd',
  reduce: 'trading.signals.sideReduce',
  hold: 'trading.signals.sideHold',
}

/** 信号方向颜色 — A股配色：红买绿卖 */
export const SIGNAL_SIDE_COLOR: Record<string, string> = {
  open: 'red',
  add: 'volcano',
  reduce: 'green',
  hold: 'default',
}

/** 策略实例状态 — 新模型 (running/stopped/error) */
export const STRATEGY_INSTANCE_STATUS_KEYS: Record<string, string> = {
  running: 'trading.strategyInstance.statusRunning',
  stopped: 'trading.strategyInstance.statusStopped',
  error: 'trading.strategyInstance.statusError',
}

export const STRATEGY_INSTANCE_STATUS_COLOR: Record<string, string> = {
  running: 'success',
  stopped: 'default',
  error: 'error',
}

/** 策略实例运行模式 */
export const RUN_MODE_KEYS: Record<string, string> = {
  paper: 'trading.strategyInstance.runModePaper',
  live: 'trading.strategyInstance.runModeLive',
  paper_to_live: 'trading.strategyInstance.runModePaperToLive',
}

/** 模拟盘会话状态 */
export const PAPER_SESSION_STATUS_KEYS: Record<string, string> = {
  running: 'trading.paper.sessionStatusRunning',
  paused: 'trading.paper.sessionStatusPaused',
  stopped: 'trading.paper.sessionStatusStopped',
}

export const PAPER_SESSION_STATUS_COLOR: Record<string, string> = {
  running: 'success',
  paused: 'warning',
  stopped: 'default',
}

/** 交易账户类型 */
export const ACCOUNT_TYPE_KEYS: Record<string, string> = {
  paper: 'trading.account.typePaper',
  live: 'trading.account.typeLive',
}

export const ACCOUNT_TYPE_COLOR: Record<string, string> = {
  paper: 'blue',
  live: 'gold',
}

export function getSideLabel(side: string): string {
  return SIDE_KEYS[side] ?? side
}

export function getStatusLabel(status: string): string {
  return STATUS_KEYS[status] ?? status
}
