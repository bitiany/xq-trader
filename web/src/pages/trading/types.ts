export interface KpiData {
  totalAsset: number;
  availableCash: number;
  marketValue: number;
  todayPnl: number;
  todayPnlPct: number;
  cumulativePnl: number;
  cumulativePnlPct: number;
  maxDrawdownPct: number;
}

export type SignalSide = 'open' | 'add' | 'reduce' | 'close';
export type InstanceStatus = 'draft' | 'running' | 'paused' | 'stopped';
export type RunMode = 'live_manual' | 'live_auto' | 'paper' | 'backtest';
export type OrderSide = 'buy' | 'sell';
export type OrderStatus =
  | 'created'
  | 'risk_checked'
  | 'submitted'
  | 'partial_filled'
  | 'filled'
  | 'cancelled'
  | 'rejected'
  | 'expired';
export type RiskLevel = 'info' | 'warn' | 'critical' | 'fatal';
export type PositionSizingStrategy =
  | 'watchlist_target_weight'
  | 'equal_weight'
  | 'confidence_weighted';
