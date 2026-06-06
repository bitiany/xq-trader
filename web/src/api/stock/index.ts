import { request } from '@/api/client'
import type { ApiPageResult } from '@/api/types'

export type IndicatorKind = 'ma' | 'macd' | 'kdj' | 'rsi' | 'bias'

export interface StockTagItem {
  tag_key: string
  tag_name: string
  dimension: string
  score: number | null
  confidence: string | null
}

export interface TagDefinitionItem {
  tag_key: string
  tag_name: string
  dimension: string
  description: string | null
  rule_engine: string
  rebalance_freq: string
  status: string
}

export interface StockSearchItem {
  symbol: string
  code: string
  name: string
  industry: string
  market: string
}

export interface StockQuoteSnapshot {
  symbol: string
  last: number | null
  prev_close: number | null
  change: number | null
  change_pct: number | null
  open: number | null
  high: number | null
  low: number | null
  volume: number | null
  amount: number | null
  timestamp: string | null
  status: string
  source: string
}

export interface StockValuationPanel {
  trade_date: string | null
  close: number | null
  pe: number | null
  pe_ttm: number | null
  pb: number | null
  ps: number | null
  ps_ttm: number | null
  dv_ratio: number | null
  total_mv: number | null
  circ_mv: number | null
  turnover_rate: number | null
}

export interface StockOverviewResponse {
  symbol: string
  code: string
  name: string
  industry: string
  market: string
  exchange: string
  list_date: string
  introduction: string | null
  quote: StockQuoteSnapshot
  valuation: StockValuationPanel
  tags: StockTagItem[]
}

export interface KlineBarItem {
  trade_date: string
  open: number
  close: number
  high: number
  low: number
  volume: number
  amount: number
  pct_chg: number | null
}

export interface StockKlineResponse {
  symbol: string
  bars: KlineBarItem[]
  indicator: IndicatorKind
  overlays: Record<string, Record<string, Array<number | null>>>
  ma_overlays: Record<string, Array<number | null>>
}

export interface StockNewsItem {
  id: string
  title: string
  source: string
  published_at: string
  summary: string | null
  url: string | null
}

export interface StockNewsResponse {
  symbol: string
  items: StockNewsItem[]
  placeholder: boolean
}

export interface FinancialReportSummary {
  end_date: string | null
  ann_date: string | null
  highlights: Record<string, number | string | null>
}

export interface StockFinancialsResponse {
  symbol: string
  income_statement: FinancialReportSummary | null
  balance_sheet: FinancialReportSummary | null
  cash_flow: FinancialReportSummary | null
  financial_indicator: FinancialReportSummary | null
}

export interface StockDiagnosisResponse {
  symbol: string
  available: boolean
  message: string
}

export async function searchStocks(query: string, limit = 20): Promise<StockSearchItem[]> {
  return request.get<StockSearchItem[]>('/stocks/search', { params: { q: query, limit } })
}

export async function fetchStockOverview(symbol: string): Promise<StockOverviewResponse> {
  return request.get<StockOverviewResponse>(`/stocks/${encodeURIComponent(symbol)}`)
}

export async function fetchStockKline(symbol: string, indicator: IndicatorKind = 'ma'): Promise<StockKlineResponse> {
  return request.get<StockKlineResponse>(`/stocks/${encodeURIComponent(symbol)}/kline`, {
    params: { indicator },
  })
}

export async function fetchStockKlineBars(symbol: string): Promise<KlineBarItem[]> {
  return request.get<KlineBarItem[]>(`/stocks/${encodeURIComponent(symbol)}/kline/bars`)
}

export async function fetchStockNews(symbol: string): Promise<StockNewsResponse> {
  return request.get<StockNewsResponse>(`/stocks/${encodeURIComponent(symbol)}/news`)
}

export async function fetchStockFinancials(symbol: string): Promise<StockFinancialsResponse> {
  return request.get<StockFinancialsResponse>(`/stocks/${encodeURIComponent(symbol)}/financials`)
}

export async function fetchStockDiagnosis(symbol: string): Promise<StockDiagnosisResponse> {
  return request.get<StockDiagnosisResponse>(`/stocks/${encodeURIComponent(symbol)}/diagnosis`)
}

export interface StockListItem {
  symbol: string
  code: string
  name: string
  industry: string
  market: string
  cnspell: string
  close: number | null
  change_pct: number | null
  pe_ttm: number | null
  pb: number | null
  total_mv: number | null
  turnover_rate: number | null
  roe: number | null
  grossprofit_margin: number | null
  dv_ratio: number | null
  tags: StockTagItem[]
}

export interface StockListParams {
  page?: number
  page_size?: number
  market?: string
  industry?: string
  list_status?: string
  q?: string
  tag_keys?: string
  exclude_st?: boolean
}

export async function fetchStockList(params: StockListParams = {}): Promise<ApiPageResult<StockListItem>> {
  return request.get<ApiPageResult<StockListItem>>('/stocks', { params })
}

export interface ChanlunFractal {
  index: number
  trade_date: string
  price: number
  direction: 'top' | 'bottom'
}

export interface ChanlunStroke {
  start_index: number
  start_date: string
  start_price: number
  end_index: number
  end_date: string
  end_price: number
  direction: 'up' | 'down'
}

export interface ChanlunPivot {
  start_index: number
  start_date: string
  end_index: number
  end_date: string
  zg: number
  zd: number
  zz: number
}

export interface ChanlunResponse {
  fractals: ChanlunFractal[]
  strokes: ChanlunStroke[]
  pivots: ChanlunPivot[]
}

export async function fetchStockChanlun(symbol: string): Promise<ChanlunResponse> {
  return request.get<ChanlunResponse>(`/stocks/${encodeURIComponent(symbol)}/chanlun`)
}

export function buildStockQuoteTopic(symbol: string): string {
  return `market.stock.${symbol}`
}

export async function fetchTagDefinitions(): Promise<TagDefinitionItem[]> {
  return request.get<TagDefinitionItem[]>('/stocks/tags/definitions')
}

export async function fetchStockTags(symbol: string): Promise<StockTagItem[]> {
  return request.get<StockTagItem[]>(`/stocks/tags/${encodeURIComponent(symbol)}`)
}
