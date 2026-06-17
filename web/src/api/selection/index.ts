import { request } from '@/api/client'
import type { ApiPageResult } from '@/api/types'

export type UniverseType = 'full_market' | 'index' | 'custom'

export interface SelectionRunPayload {
  strategy_id: string
  signal_date: string
  universe_type: UniverseType
  universe_param?: string | null
  custom_symbols?: string[] | null
  top_n: number
}

export interface SelectionItem {
  rank: number
  symbol: string
  name: string
  industry: string
  close: number | null
  pct_chg: number | null
  score: number
  direction: string | null
  confidence: number | null
  factor_values: Record<string, number | null>
}

export interface SelectionFilterStep {
  step_type: 'universe' | 'rule' | 'group' | 'final'
  label: string
  count: number
  pass_rate: number
  group_id?: number
  group_method?: string
  rule_id?: string
  expression?: string | null
  spi_class?: string | null
  factors?: string[]
  weight?: number
  threshold?: number | null
}

export interface SelectionRunResponse {
  strategy_id: string
  signal_date: string
  universe_type: UniverseType
  universe_size: number
  selected_count: number
  elapsed_ms: number
  items: SelectionItem[]
  factor_labels: Record<string, string>
  filter_steps: SelectionFilterStep[]
}

export interface SelectionResult {
  id?: number
  strategy_id: string
  signal_date: string
  instance_id?: string | null
  rank: number
  symbol: string
  name: string | null
  score: number
  direction: string | null
  confidence: number | null
  factor_values_flat: Record<string, number | null> | null
  factor_values?: Record<string, number | null> | null
  created_at?: string
}

export interface SelectionResultsParams {
  strategy_id?: string
  signal_date?: string
  instance_id?: string
  page?: number
  page_size?: number
}

export interface SelectionDatesParams {
  strategy_id?: string
  instance_id?: string
}

export async function runSelection(payload: SelectionRunPayload): Promise<SelectionRunResponse> {
  return request.post<SelectionRunResponse>('/selection/run', payload)
}

export async function fetchSelectionResults(
  params: SelectionResultsParams,
): Promise<ApiPageResult<SelectionResult>> {
  return request.get<ApiPageResult<SelectionResult>>('/selection/results', { params })
}

export async function fetchSelectionDates(
  params: SelectionDatesParams,
): Promise<string[]> {
  return request.get<string[]>('/selection/results/dates', { params })
}
