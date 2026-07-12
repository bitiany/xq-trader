import { request } from '@/api/client'

// ==================== 盘内信号 ====================

export interface IntradaySignal {
  id: number
  instance_id: number
  workflow_run_id: string | null
  signal_date: string
  symbol: string
  name?: string
  direction: 'long' | 'short' | 'neutral'
  strength: number | null
  signal_type: string | null
  signal_source: string
  raw_values: Record<string, unknown> | null
  selection_id: number | null
  node_id: string | null
  created_at: string
  updated_at: string
}

export interface IntradaySignalListResponse {
  items: IntradaySignal[]
  total: number
  page: number
  page_size: number
}

export async function fetchIntradaySignals(params: {
  trade_date?: string
  symbol?: string
  signal_type?: string
  direction?: string
  signal_source?: string
  page?: number
  page_size?: number
}): Promise<IntradaySignalListResponse> {
  return request.get('/intraday/signals', { params })
}

// ==================== 盘内状态 ====================

export interface IntradayStatus {
  running: boolean
  monitoring: boolean
}

export async function fetchIntradayStatus(): Promise<IntradayStatus> {
  return request.get('/intraday/status')
}

export async function startIntradayMonitor(): Promise<{ message: string }> {
  return request.post('/intraday/start')
}

export async function stopIntradayMonitor(): Promise<{ message: string }> {
  return request.post('/intraday/stop')
}

// ==================== 动态股票池 ====================

export interface DynamicPoolResponse {
  symbols: string[]
  count: number
}

export async function fetchDynamicPool(): Promise<DynamicPoolResponse> {
  return request.get('/intraday/pool')
}

// ==================== 分钟线 ====================

export interface MinuteBar {
  symbol: string
  trade_time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  amount: number
  trade_date: string
}

export interface MinuteBarsResponse {
  symbol: string
  bars: MinuteBar[]
  count: number
}

export async function fetchMinuteBars(
  symbol: string,
  tradeDate?: string,
  limit?: number,
): Promise<MinuteBarsResponse> {
  return request.get('/intraday/minute-bars', {
    params: { symbol, trade_date: tradeDate, limit },
  })
}
