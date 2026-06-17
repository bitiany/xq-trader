import { request } from '@/api/client'
import type { ApiPageResult } from '@/api/types'

export type FactorDirection = 'DESC' | 'ASC'
export type FactorStatus = 'draft' | 'testing' | 'active' | 'deprecated'

export interface Factor {
  id?: number
  factor_id: string
  display_name: string
  category: string
  direction: FactorDirection
  description: string | null
  status: FactorStatus
  factor_grade?: string | null
  scope?: string | null
  signal_type?: string | null
  group_id?: string | null
  compute_engine?: string | null
  compute_module?: string | null
  data_origin?: string | null
  dependencies?: string[] | null
  base_factor?: string | null
  min_periods?: number | null
  tags?: string[] | null
  updated_at?: string
}

export interface FactorListParams {
  page?: number
  page_size?: number
  category?: string
  status?: FactorStatus
  keyword?: string
}

export interface FactorCategoryStat {
  category: string
  count: number
}

export interface FactorValue {
  factor_id: string
  symbol: string
  trade_date: string
  value: number | null
  pool_id?: string | null
}

export interface FactorStats {
  factor_id: string
  pool_id: string
  calc_date: string
  ic_mean: number | null
  ic_std: number | null
  icir: number | null
  ic_win_rate: number | null
  turnover: number | null
  decay_half_life: number | null
  long_short_annual_ret: number | null
  long_short_sharpe: number | null
  coverage: number | null
  factor_grade?: string | null
}

export interface FactorValuesParams {
  trade_date?: string
  pool_id?: string
  symbols?: string
  limit?: number
}

export interface FactorStatsParams {
  pool_id?: string
  start_date?: string
  end_date?: string
  limit?: number
}

export async function fetchFactors(params: FactorListParams = {}): Promise<ApiPageResult<Factor>> {
  return request.get<ApiPageResult<Factor>>('/factors', { params })
}

export async function fetchFactorCategories(): Promise<FactorCategoryStat[]> {
  return request.get<FactorCategoryStat[]>('/factors/categories')
}

export async function fetchFactorDetail(factorId: string): Promise<Factor> {
  return request.get<Factor>(`/factors/${encodeURIComponent(factorId)}`)
}

export async function fetchFactorValues(
  factorId: string,
  params: FactorValuesParams = {},
): Promise<FactorValue[]> {
  return request.get<FactorValue[]>(`/factors/${encodeURIComponent(factorId)}/values`, { params })
}

export async function fetchFactorStats(
  factorId: string,
  params: FactorStatsParams = {},
): Promise<FactorStats[]> {
  return request.get<FactorStats[]>(`/factors/${encodeURIComponent(factorId)}/stats`, { params })
}

export async function fetchFactorStatsLatest(
  factorId: string,
  poolId?: string,
): Promise<FactorStats | null> {
  return request.get<FactorStats | null>(
    `/factors/${encodeURIComponent(factorId)}/stats/latest`,
    { params: poolId ? { pool_id: poolId } : undefined },
  )
}
