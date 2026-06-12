export interface Account {
  value: string;
  label: string;
  broker: string;
}

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

export interface PreOrder {
  id: string;
  symbol: string;
  name: string;
  side: SignalSide;
  suggestedQty: number;
  suggestedPrice: number;
  priceType: 'limit' | 'market';
  targetWeight: number;
  currentWeight: number;
  sizingStrategy: string;
  availableCash: number;
  reason: string;
  signalDate: string;
  executionDate: string;
}

export interface DeviationAlert {
  symbol: string;
  name: string;
  targetWeight: number;
  currentWeight: number;
  deviation: number;
}

export interface RiskStatus {
  circuitBreakerTriggered: boolean;
  todayBlocked: number;
  activeAlerts: number;
  activeRules: number;
  dailyLossPct: number;
  maxDrawdownPct: number;
  deviationAlerts: DeviationAlert[];
}

export type InstanceStatus = 'running' | 'stopped' | 'error';
export type RunMode = 'paper' | 'live';

export interface StrategyInstance {
  id: string;
  code: string;
  name: string;
  runMode: RunMode;
  status: InstanceStatus;
  positionSizing: string;
  cumulativePnl: number;
  maxDrawdown: number;
  totalCycles: number;
  lastRunAt: string;
  nextRunAt: string;
  stockPool: number;
  pendingApprovals: number;
}

export interface StockItem {
  symbol: string;
  name: string;
  lastPrice: number;
  changePct: number;
  industry: string;
  marketValue: string;
}

export interface WatchlistItem extends StockItem {
  tags: string[];
}

export interface Position {
  symbol: string;
  name: string;
  targetWeight: number;
  actualWeight: number;
  deviation: number;
  costPrice: number;
  lastPrice: number;
  pnl: number;
  pnlPct: number;
  todayPnl: number;
}

export type OrderSide = 'buy' | 'sell';
export type OrderStatus = 'filled' | 'partial_filled' | 'submitted' | 'rejected' | 'cancelled' | 'expired';

export interface Order {
  id: string;
  time: string;
  symbol: string;
  name: string;
  side: OrderSide;
  qty: number;
  price: number;
  status: OrderStatus;
  strategy: string;
}

export interface WorkflowStep {
  title: string;
  status: 'wait' | 'process' | 'finish' | 'error';
}

export type RiskLevel = 'info' | 'warn' | 'critical' | 'fatal';
export type RiskCategory = 'circuit_breaker' | 'position' | 'capital' | 'timing';

export interface RiskRule {
  code: string;
  name: string;
  category: RiskCategory;
  level: RiskLevel;
  enabled: boolean;
  params: string;
}

export interface SignalHistoryItem {
  signalDate: string;
  symbol: string;
  name: string;
  direction: SignalSide;
  status: 'filled' | 'rejected';
  approvedBy: string;
  result: string;
}

export type PositionSizingStrategy = 'equal_weight' | 'signal_weighted' | 'atr_risk' | 'inverse_volatility' | 'kelly' | 'vol_target' | 'fixed_pct';

export type WfStatus = 'succeeded' | 'running' | 'pending' | 'failed';
