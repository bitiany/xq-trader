import { request } from '@/api/client'
import type { ApiPageResult } from '@/api/types'

export type StrategyStatus = 'draft' | 'active' | 'deprecated'
export type StrategyType = 'selection' | 'timing'
export type CombinationMethod = 'and' | 'or' | 'weighted_score' | 'weighted_vote' | 'ic_weighted'

/** 旧版回测页规则组合器（保留以兼容历史代码引用） */
export type Combinator = 'AND' | 'OR' | 'VOTING'

export interface Strategy {
  id?: number
  strategy_id: string
  name: string
  description: string | null
  strategy_type: StrategyType
  config: Record<string, unknown>
  status: StrategyStatus
  created_at?: string
  updated_at?: string
}

export interface RuleRegistryItem {
  rule_id: string
  name?: string
  category?: string
  rule_type?: string
  definition?: Record<string, unknown>
  description?: string | null
  status?: string
  [key: string]: unknown
}

export interface StrategyDetail extends Strategy {
  rule_registry?: Record<string, RuleRegistryItem>
}

export interface StrategyListParams {
  page?: number
  page_size?: number
  status?: StrategyStatus
  strategy_type?: StrategyType
  keyword?: string
}

export interface StrategyCreatePayload {
  strategy_id: string
  name: string
  description?: string | null
  strategy_type?: StrategyType
  config?: Record<string, unknown>
  status?: StrategyStatus
}

export interface StrategyUpdatePayload {
  name?: string
  description?: string | null
  strategy_type?: StrategyType
  config?: Record<string, unknown>
  status?: StrategyStatus
}

export interface StrategyDeleteResult {
  strategy_id: string
  deleted: boolean
}

export async function fetchStrategies(
  params: StrategyListParams = {},
): Promise<ApiPageResult<Strategy>> {
  return request.get<ApiPageResult<Strategy>>('/strategies', { params })
}

export async function fetchStrategyDetail(strategyId: string): Promise<StrategyDetail> {
  return request.get<StrategyDetail>(`/strategies/${encodeURIComponent(strategyId)}`)
}

export async function createStrategy(payload: StrategyCreatePayload): Promise<Strategy> {
  return request.post<Strategy>('/strategies', payload)
}

export async function updateStrategy(
  strategyId: string,
  payload: StrategyUpdatePayload,
): Promise<Strategy> {
  return request.put<Strategy>(`/strategies/${encodeURIComponent(strategyId)}`, payload)
}

export async function deleteStrategy(strategyId: string): Promise<StrategyDeleteResult> {
  return request.delete<StrategyDeleteResult>(`/strategies/${encodeURIComponent(strategyId)}`)
}
