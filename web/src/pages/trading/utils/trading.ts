import type { OrderStatus, OrderSide, SignalSide, InstanceStatus, RunMode, RiskLevel, PositionSizingStrategy } from '../types';

export const formatMoney = (v: number): string => {
  if (v >= 1e6) return `¥${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `¥${(v / 1e3).toFixed(1)}K`;
  return `¥${v.toFixed(2)}`;
};

export const formatPct = (v: number): string => {
  const sign = v > 0 ? '+' : '';
  return `${sign}${(v * 100).toFixed(2)}%`;
};

export const STATUS_COLOR: Record<OrderStatus, string> = {
  filled: 'success',
  partial_filled: 'warning',
  submitted: 'processing',
  rejected: 'error',
  cancelled: 'default',
  expired: 'default',
};

export const STATUS_LABEL: Record<OrderStatus, string> = {
  filled: '已成交',
  partial_filled: '部成',
  submitted: '已报',
  rejected: '废单',
  cancelled: '已撤',
  expired: '过期',
};

export const SIDE_COLOR: Record<OrderSide, string> = { buy: 'var(--color-rise)', sell: 'var(--color-fall)' };
export const SIDE_LABEL: Record<OrderSide, string> = { buy: '买入', sell: '卖出' };

export const SIGNAL_SIDE_LABEL: Record<SignalSide, string> = { open: '开仓', add: '加仓', reduce: '减仓', close: '平仓' };
export const SIGNAL_SIDE_COLOR: Record<SignalSide, string> = { open: 'var(--color-rise)', add: 'var(--color-rise)', reduce: 'var(--color-fall)', close: 'var(--color-fall)' };
export const SIGNAL_SIDE_CLASS: Record<SignalSide, string> = {
  open: 'signal-card--open',
  add: 'signal-card--add',
  reduce: 'signal-card--reduce',
  close: 'signal-card--close',
};

export const INSTANCE_STATUS_COLOR: Record<InstanceStatus, string> = { running: 'success', stopped: 'default', error: 'error' };
export const INSTANCE_STATUS_LABEL: Record<InstanceStatus, string> = { running: '运行中', stopped: '已停止', error: '异常' };
export const RUN_MODE_LABEL: Record<RunMode, string> = { paper: '模拟盘', live: '实盘' };

export const POSITION_SIZING_OPTIONS: { value: PositionSizingStrategy; label: string }[] = [
  { value: 'equal_weight', label: '等权' },
  { value: 'signal_weighted', label: '信号加权' },
  { value: 'atr_risk', label: 'ATR 风险定仓' },
  { value: 'inverse_volatility', label: '逆波动率' },
  { value: 'kelly', label: '凯利半仓' },
  { value: 'vol_target', label: '波动率目标' },
  { value: 'fixed_pct', label: '固定比例' },
];

export const WF_STATUS_COLOR: Record<string, string> = {
  succeeded: 'var(--color-fall)',
  running: 'var(--accent-primary)',
  pending: 'var(--text-secondary)',
  failed: 'var(--color-rise)',
};

export const RISK_LEVEL_TAG: Record<RiskLevel, string> = { info: 'default', warn: 'warning', critical: 'error', fatal: 'error' };
