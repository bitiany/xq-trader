import { request } from '@/api/client'
import type { Strategy } from '@/api/strategy'

export type BacktestStrategyInfo = Strategy

interface StrategyPageData {
  items: BacktestStrategyInfo[]
}

export async function fetchBacktestStrategies(): Promise<BacktestStrategyInfo[]> {
  const page = await request.get<StrategyPageData>('/strategies', {
    params: { status: 'active', strategy_type: 'timing', page_size: 200 },
  })
  return page.items
}

export interface TradeRecord {
  date: string
  symbol: string
  direction: 'buy' | 'sell'
  price: number
  quantity: number
  value: number
  signal_reason: string
}

export interface PositionRecord {
  date: string
  symbol: string
  quantity: number
  avg_cost: number
  market_value: number
  pnl: number
  pnl_pct: number
  weight: number
}

export interface SimpleBacktestRequest {
  strategy_id: string
  symbols: string[]
  start_date: string
  end_date: string
  initial_cash?: number
  commission?: number
}

export interface BacktestSymbolMetrics {
  total_return?: number
  annual_return?: number
  annualized_return?: number
  avg_daily_return?: number
  max_drawdown?: number
  max_dd_length?: number
  sharpe_ratio?: number
  total_trades?: number
  num_trades?: number
  win_rate?: number
  profit_loss_ratio?: number
  sqn?: number
  final_value?: number
  initial_cash?: number
  equity_curve?: { date: string; value: number }[]
  trades?: TradeRecord[]
  positions?: PositionRecord[]
  ohlcv?: { date: string; open: number; close: number; high: number; low: number; volume: number }[]
}

export interface SimpleBacktestResponse {
  run_id: string
  strategy_id: string
  status: string
  metrics_per_symbol: Record<string, BacktestSymbolMetrics>
}

export async function runSimpleBacktest(payload: SimpleBacktestRequest): Promise<SimpleBacktestResponse> {
  return request.post<SimpleBacktestResponse>('/backtest/run', payload)
}
