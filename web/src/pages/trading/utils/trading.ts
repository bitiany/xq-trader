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
  created: 'default',
  risk_checked: 'processing',
  submitted: 'processing',
  partial_filled: 'warning',
  filled: 'success',
  cancelled: 'default',
  rejected: 'error',
  expired: 'default',
};

export const STATUS_LABEL: Record<OrderStatus, string> = {
  created: '已创建',
  risk_checked: '风控通过',
  submitted: '已报',
  partial_filled: '部成',
  filled: '已成交',
  cancelled: '已撤',
  rejected: '废单',
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

export const DEFAULT_OPERATOR = 'personal';
export const DIRECTION_LABEL: Record<string, string> = { long: '看多', short: '看空', neutral: '中性' };
export const DIRECTION_COLOR: Record<string, string> = { long: 'var(--color-rise)', short: 'var(--color-fall)', neutral: 'default' };

export function formatSignalPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return `${(Number(value) * 100).toFixed(0)}%`;
}

export function formatCompactPnl(value: number): string {
  const sign = value > 0 ? '+' : '';
  const abs = Math.abs(value);
  if (abs >= 1e4) return `${sign}${(value / 1e4).toFixed(1)}万`;
  if (abs >= 1e3) return `${sign}${(value / 1e3).toFixed(1)}K`;
  return `${sign}${value.toFixed(0)}`;
}

export const INSTANCE_STATUS_COLOR: Record<InstanceStatus, string> = { draft: 'default', running: 'success', paused: 'warning', stopped: 'default' };
export const INSTANCE_STATUS_LABEL: Record<InstanceStatus, string> = { draft: '草稿', running: '运行中', paused: '已暂停', stopped: '已停止' };
export const RUN_MODE_LABEL: Record<RunMode, string> = { live_manual: '实盘(手动)', live_auto: '实盘(自动)', paper: '模拟盘', backtest: '回测' };

export const POSITION_SIZING_OPTIONS: { value: PositionSizingStrategy; label: string }[] = [
  { value: 'watchlist_target_weight', label: '自选目标权重' },
  { value: 'confidence_weighted', label: '置信度加权' },
  { value: 'equal_weight', label: '等权' },
];

export const WF_STATUS_COLOR: Record<string, string> = {
  succeeded: 'var(--color-fall)',
  running: 'var(--accent-primary)',
  pending: 'var(--text-secondary)',
  failed: 'var(--color-rise)',
};

export const RISK_LEVEL_TAG: Record<RiskLevel, string> = { info: 'default', warn: 'warning', critical: 'error', fatal: 'error' };
