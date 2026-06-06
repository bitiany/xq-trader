import { request } from '@/api/client'
import type { StockTagItem } from '@/api/stock'

export interface BacktestStrategyInfo {
  strategy_id: string
  name: string
  description: string
  mode: string
  params_schema: Record<string, unknown>
}

export interface BacktestSizerInfo {
  sizer_id: string
  name: string
  description: string
  params_schema: Record<string, unknown>
}

export interface BacktestRunRequest {
  workspace_id: string
  symbols: string[]
  strategy_id: string
  strategy_mode: string
  strategy_params: Record<string, unknown>
  sizer_id: string
  sizer_params: Record<string, unknown>
  start_date: string | null
  end_date: string | null
  benchmark: string
  initial_capital?: number
  commission_rate?: number
  stamp_tax_rate?: number
  screening_execute_id?: string | null
}

export interface BacktestPerformance {
  execute_id: string
  total_return: number
  annualized_return: number | null
  benchmark_total_return: number | null
  alpha: number | null
  beta: number | null
  sharpe_ratio: number | null
  sortino_ratio: number | null
  calmar_ratio: number | null
  max_drawdown: number | null
  max_drawdown_duration: number | null
  volatility: number | null
  win_rate: number | null
  profit_loss_ratio: number | null
  total_trades: number | null
  profitable_trades: number | null
  losing_trades: number | null
  avg_holding_days: number | null
  turnover_rate: number | null
}

export interface BacktestEquityItem {
  trade_date: string
  net_value: number
  daily_return: number | null
  cumulative_return: number | null
  benchmark_return: number | null
  drawdown: number | null
  cash: number | null
  total_value: number | null
}

export interface BacktestOrderItem {
  order_id: string
  symbol: string
  direction: string
  order_type: string
  price: number
  amount: number
  filled_amount: number
  avg_fill_price: number | null
  status: string
  commission: number | null
  reason: string | null
  signal_date: string | null
}

export interface BacktestPositionItem {
  trade_date: string
  symbol: string
  amount: number
  avg_cost: number
  current_price: number | null
  market_value: number | null
  pnl: number | null
  pnl_pct: number | null
  weight: number | null
  tags: StockTagItem[]
}

export interface BacktestResultData {
  execute_id: string
  workspace_id: string
  status: string
  strategy_id: string
  sizer_id: string
  start_date: string | null
  end_date: string | null
  total_return: number | null
  annualized_return: number | null
  sharpe_ratio: number | null
  max_drawdown: number | null
  win_rate: number | null
  total_trades: number | null
  performance: Record<string, unknown> | null
  error_message: string | null
}

interface PaginatedData<T> {
  total: number
  page: number
  page_size: number
  items: T[]
}

export async function runBacktest(payload: BacktestRunRequest): Promise<BacktestResultData> {
  return request.post<BacktestResultData>('/backtest/run', payload)
}

export async function fetchBacktestResult(executeId: string): Promise<BacktestResultData> {
  return request.get<BacktestResultData>(`/backtest/${executeId}`)
}

export async function fetchBacktestEquity(
  executeId: string,
  page = 1,
  pageSize = 500,
): Promise<PaginatedData<BacktestEquityItem>> {
  return request.get<PaginatedData<BacktestEquityItem>>(
    `/backtest/${executeId}/equity`,
    { params: { page, page_size: pageSize } },
  )
}

export async function fetchBacktestOrders(
  executeId: string,
  page = 1,
  pageSize = 50,
): Promise<PaginatedData<BacktestOrderItem>> {
  return request.get<PaginatedData<BacktestOrderItem>>(
    `/backtest/${executeId}/orders`,
    { params: { page, page_size: pageSize } },
  )
}

export async function fetchBacktestPositions(
  executeId: string,
  tradeDate?: string,
  page = 1,
  pageSize = 50,
): Promise<PaginatedData<BacktestPositionItem>> {
  const params: Record<string, unknown> = { page, page_size: pageSize }
  if (tradeDate) params.trade_date = tradeDate
  return request.get<PaginatedData<BacktestPositionItem>>(
    `/backtest/${executeId}/positions`,
    { params },
  )
}

export async function fetchBacktestPerformance(executeId: string): Promise<BacktestPerformance> {
  return request.get<BacktestPerformance>(`/backtest/${executeId}/performance`)
}

export async function fetchBacktestStrategies(): Promise<BacktestStrategyInfo[]> {
  return request.get<BacktestStrategyInfo[]>('/backtest/strategies/list')
}

export async function fetchBacktestSizers(): Promise<BacktestSizerInfo[]> {
  return request.get<BacktestSizerInfo[]>('/backtest/sizers/list')
}
