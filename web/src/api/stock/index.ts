import { request } from '@/api/client'
import type { ApiPageResult } from '@/api/types'

export type MainIndicator = 'ma' | 'boll' | 'chanlun'
export type SubIndicator = 'macd' | 'kdj' | 'rsi' | 'bias' | 'adx' | 'fundflow'

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
  overlays: Record<string, Record<string, Array<number | null>>>
  ma_overlays: Record<string, Array<number | null>>
}

export interface StockNewsItem {
  id: string
  title: string
  source: string | null
  published_at: string
  summary: string | null
  url: string | null
  keywords: string[]
}

export interface StockNewsResponse {
  symbol: string
  items: StockNewsItem[]
  total: number
}

export type StockAnnouncementsResponse = StockNewsResponse

export interface StockFundFlowItem {
  trade_date: string
  close: number | null
  pct_chg: number | null
  main_net_amt: number | null
  main_net_pct: number | null
  huge_net_amt: number | null
  huge_net_pct: number | null
  huge_net_inflow_pct: number | null
  big_net_amt: number | null
  big_net_pct: number | null
  big_net_inflow_pct: number | null
  mid_net_amt: number | null
  mid_net_pct: number | null
  mid_net_inflow_pct: number | null
  small_net_amt: number | null
  small_net_pct: number | null
  small_net_inflow_pct: number | null
}

export interface StockFundFlowResponse {
  symbol: string
  items: StockFundFlowItem[]
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
  financial_indicator_history?: FinancialReportSummary[]
}

export interface DiagnosisModuleScore {
  key: 'technical' | 'capital_flow' | 'fundamental' | 'sentiment' | 'industry' | 'institutional'
  label: string
  score: number | null
  prev_score: number | null
  weight: number
  detail: Record<string, unknown>
}

export interface DiagnosisKeyMetrics {
  pe_ttm: number | null
  pb: number | null
  dv_ttm: number | null
  institutional_hold_pct: number | null
  institutional_hold_source?: 'fund' | null
  industry_rank: number | null
  industry_total: number | null
  industry_name: string | null
}

export interface DiagnosisSummaryHighlight {
  key: string
  label: string
  segments: Array<{ text: string; highlight?: boolean }>
}

export interface DiagnosisSummary {
  bullets: string[]
  narrative?: string
  highlights?: DiagnosisSummaryHighlight[]
  generated_by: 'agent' | 'rule'
  generated_at: string
}

export interface DiagnosisEarningsPreviewItem {
  info_code: string
  title: string | null
  org_name: string | null
  rating: string | null
  publish_date: string | null
  eps_forecast: Array<Record<string, unknown>>
}

export interface DiagnosisThesisSnapshot {
  direction: string
  as_of: string
  valid_until: string
  core_assumption: string
}

export interface StockDiagnosisResponse {
  symbol: string
  name: string
  industry: string | null
  intro: string | null
  as_of: string
  overall_score: number | null
  prev_overall_score: number | null
  prev_as_of: string | null
  market_percentile: number | null
  rating_label: string | null
  module_scores: DiagnosisModuleScore[]
  key_metrics: DiagnosisKeyMetrics
  summary: DiagnosisSummary
  thesis: DiagnosisThesisSnapshot | null
  reports_count: number
  cached?: boolean
}

export interface StockDiagnosisHistoryItem {
  as_of: string
  overall_score: number | null
  modules: Record<string, number | null>
}

export interface StockDiagnosisHistoryResponse {
  symbol: string
  items: StockDiagnosisHistoryItem[]
}

export async function searchStocks(query: string, limit = 20): Promise<StockSearchItem[]> {
  return request.get<StockSearchItem[]>('/stocks/search', { params: { q: query, limit } })
}

export async function fetchStockOverview(symbol: string): Promise<StockOverviewResponse> {
  return request.get<StockOverviewResponse>(`/stocks/${encodeURIComponent(symbol)}`)
}

export async function fetchStockKline(symbol: string): Promise<StockKlineResponse> {
  return request.get<StockKlineResponse>(`/stocks/${encodeURIComponent(symbol)}/kline`)
}

export async function fetchStockKlineBars(symbol: string): Promise<KlineBarItem[]> {
  return request.get<KlineBarItem[]>(`/stocks/${encodeURIComponent(symbol)}/kline/bars`)
}

export async function fetchStockNews(symbol: string): Promise<StockNewsResponse> {
  return request.get<StockNewsResponse>(`/stocks/${encodeURIComponent(symbol)}/news`)
}

export async function fetchStockAnnouncements(symbol: string): Promise<StockAnnouncementsResponse> {
  return request.get<StockAnnouncementsResponse>(`/stocks/${encodeURIComponent(symbol)}/announcements`)
}

export async function fetchStockFundFlow(symbol: string, limit = 120): Promise<StockFundFlowResponse> {
  return request.get<StockFundFlowResponse>(`/stocks/${encodeURIComponent(symbol)}/fund-flow`, {
    params: { limit },
  })
}

export async function fetchStockFinancials(symbol: string): Promise<StockFinancialsResponse> {
  return request.get<StockFinancialsResponse>(`/stocks/${encodeURIComponent(symbol)}/financials`)
}

export async function fetchStockDiagnosis(
  symbol: string,
  refresh = false,
): Promise<StockDiagnosisResponse> {
  return request.get<StockDiagnosisResponse>(`/stocks/${encodeURIComponent(symbol)}/diagnosis`, {
    params: refresh ? { refresh: true } : undefined,
  })
}

export async function fetchStockDiagnosisHistory(
  symbol: string,
  days = 90,
): Promise<StockDiagnosisHistoryResponse> {
  return request.get<StockDiagnosisHistoryResponse>(
    `/stocks/${encodeURIComponent(symbol)}/diagnosis/history`,
    { params: { days } },
  )
}

export interface DiagnosisSummaryTriggerResponse {
  symbol: string
  task_id: string
  status: string
}

export async function triggerStockDiagnosisSummary(
  symbol: string,
): Promise<DiagnosisSummaryTriggerResponse> {
  return request.post<DiagnosisSummaryTriggerResponse>(
    `/stocks/${encodeURIComponent(symbol)}/diagnosis/summary`,
  )
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
  is_sure: boolean
}

export interface ChanlunPivot {
  start_index: number
  start_date: string
  end_index: number
  end_date: string
  zg: number
  zd: number
  zz: number
  is_sure: boolean
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
  // 与后端 WsTopic.MARKET_STOCK_QUOTE_PREFIX 对齐，前缀匹配单例 job
  return `ws.market.stock_quotes.${symbol}`
}

export async function fetchTagDefinitions(): Promise<TagDefinitionItem[]> {
  return request.get<TagDefinitionItem[]>('/stocks/tags/definitions')
}

export async function fetchStockTags(symbol: string): Promise<StockTagItem[]> {
  return request.get<StockTagItem[]>(`/stocks/tags/${encodeURIComponent(symbol)}`)
}

// ==================== 截面因子 ====================

export interface FactorMeta {
  factor_id: string
  display_name: string
  category: string
  direction: string
  signal_type: string
  data_origin: string
  factor_grade: string | null
  is_composite: boolean
  composite_method: string | null
  description: string | null
  latest_stats: FactorStats | null
}

export interface FactorStats {
  factor_id: string
  pool_id: string
  calc_date: string
  window: number
  ic_mean: number | null
  ic_std: number | null
  icir: number | null
  ic_win_rate: number | null
  turnover: number | null
  coverage: number | null
  factor_grade: string | null
  long_short_annual_ret: number | null
  long_short_sharpe: number | null
}

export interface FactorSeriesResponse {
  symbol: string
  pool_id: string
  start_date: string
  end_date: string
  factor_count: number
  factors: FactorMeta[]
  columns: string[]
  rows: Array<Record<string, string | number | null>>
}

export async function fetchStockFactorSeries(
  symbol: string,
  days = 10,
): Promise<FactorSeriesResponse> {
  return request.get<FactorSeriesResponse>(`/factors/series/${encodeURIComponent(symbol)}`, {
    params: { days },
  })
}
