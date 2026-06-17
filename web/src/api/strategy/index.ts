import { request } from '@/api/client'
import type { ApiPageResult } from '@/api/types'

export type StrategyStatus = 'draft' | 'active' | 'deprecated'

export type RuleGroupType = 'cross_section' | 'time_series'

export type CombinationMethod =
  | 'and'
  | 'or'
  | 'weighted_score'
  | 'weighted_vote'
  | 'ic_weighted'

/** 旧版回测页规则组合器（保留以兼容历史代码引用） */
export type Combinator = 'AND' | 'OR' | 'VOTING'

export interface CrossSectionConfig {
  ranking_field?: string | null
  top_n?: number | null
  ascending?: boolean | null
  [key: string]: unknown
}

export interface TimeSeriesConfig {
  buy_threshold?: number | null
  sell_threshold?: number | null
  [key: string]: unknown
}

export interface PositionSizingConfig {
  method?: string | null
  params?: Record<string, unknown> | null
  [key: string]: unknown
}

export interface RiskOverrides {
  [key: string]: unknown
}

export interface Strategy {
  id?: number
  strategy_id: string
  name: string
  description: string | null
  cross_section_config: CrossSectionConfig | null
  time_series_config: TimeSeriesConfig | null
  position_sizing_config: PositionSizingConfig | null
  risk_overrides: RiskOverrides | null
  universe_pool: string | null
  status: StrategyStatus
  created_at?: string
  updated_at?: string
}

export interface RuleBindingRuleInfo {
  rule_id: string
  name: string
  category?: string
  type?: string
  is_builtin?: boolean
  expression?: string | null
  spi_class?: string | null
  factors?: string[]
  description?: string | null
}

export interface RuleBinding {
  id?: number
  group_id?: number
  rule_id: string
  weight: number
  config_override: Record<string, unknown> | null
  sort_order: number
  rule?: RuleBindingRuleInfo
}

export interface RuleGroup {
  id?: number
  strategy_id: string
  group_type: RuleGroupType
  combination_method: CombinationMethod
  combination_params: Record<string, unknown> | null
  threshold: number | null
  bindings?: RuleBinding[]
}

export interface StrategyDetail extends Strategy {
  rule_groups?: RuleGroup[]
}

export interface StrategyListParams {
  page?: number
  page_size?: number
  status?: StrategyStatus
  keyword?: string
}

export interface StrategyCreatePayload {
  strategy_id: string
  name: string
  description?: string | null
  cross_section_config?: CrossSectionConfig | null
  time_series_config?: TimeSeriesConfig | null
  position_sizing_config?: PositionSizingConfig | null
  risk_overrides?: RiskOverrides | null
  universe_pool?: string | null
  status?: StrategyStatus
}

export interface StrategyUpdatePayload {
  name?: string
  description?: string | null
  cross_section_config?: CrossSectionConfig | null
  time_series_config?: TimeSeriesConfig | null
  position_sizing_config?: PositionSizingConfig | null
  risk_overrides?: RiskOverrides | null
  universe_pool?: string | null
  status?: StrategyStatus
}

export interface RuleGroupCreatePayload {
  group_type: RuleGroupType
  combination_method: CombinationMethod
  combination_params?: Record<string, unknown> | null
  threshold?: number | null
}

export interface RuleGroupUpdatePayload {
  combination_method?: CombinationMethod
  combination_params?: Record<string, unknown> | null
  threshold?: number | null
}

export interface RuleBindingCreatePayload {
  rule_id: string
  weight?: number
  config_override?: Record<string, unknown> | null
  sort_order?: number
}

export interface RuleBindingUpdatePayload {
  weight?: number
  config_override?: Record<string, unknown> | null
  sort_order?: number
}

export interface StrategyDeleteResult {
  strategy_id: string
  deleted: boolean
}

export interface DeletedResult {
  deleted: boolean
}

/* -------------------------------- Strategy -------------------------------- */

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

/* ------------------------------- Rule Groups ------------------------------ */

export async function fetchRuleGroups(strategyId: string): Promise<RuleGroup[]> {
  return request.get<RuleGroup[]>(
    `/strategies/${encodeURIComponent(strategyId)}/rule-groups`,
  )
}

export async function createRuleGroup(
  strategyId: string,
  payload: RuleGroupCreatePayload,
): Promise<RuleGroup> {
  return request.post<RuleGroup>(
    `/strategies/${encodeURIComponent(strategyId)}/rule-groups`,
    payload,
  )
}

export async function updateRuleGroup(
  strategyId: string,
  groupId: number,
  payload: RuleGroupUpdatePayload,
): Promise<RuleGroup> {
  return request.put<RuleGroup>(
    `/strategies/${encodeURIComponent(strategyId)}/rule-groups/${groupId}`,
    payload,
  )
}

export async function deleteRuleGroup(
  strategyId: string,
  groupId: number,
): Promise<DeletedResult> {
  return request.delete<DeletedResult>(
    `/strategies/${encodeURIComponent(strategyId)}/rule-groups/${groupId}`,
  )
}

/* ------------------------------ Rule Bindings ----------------------------- */

export async function fetchRuleBindings(
  strategyId: string,
  groupId: number,
): Promise<RuleBinding[]> {
  return request.get<RuleBinding[]>(
    `/strategies/${encodeURIComponent(strategyId)}/rule-groups/${groupId}/bindings`,
  )
}

export async function createRuleBinding(
  strategyId: string,
  groupId: number,
  payload: RuleBindingCreatePayload,
): Promise<RuleBinding> {
  return request.post<RuleBinding>(
    `/strategies/${encodeURIComponent(strategyId)}/rule-groups/${groupId}/bindings`,
    payload,
  )
}

export async function updateRuleBinding(
  strategyId: string,
  groupId: number,
  bindingId: number,
  payload: RuleBindingUpdatePayload,
): Promise<RuleBinding> {
  return request.put<RuleBinding>(
    `/strategies/${encodeURIComponent(strategyId)}/rule-groups/${groupId}/bindings/${bindingId}`,
    payload,
  )
}

export async function deleteRuleBinding(
  strategyId: string,
  groupId: number,
  bindingId: number,
): Promise<DeletedResult> {
  return request.delete<DeletedResult>(
    `/strategies/${encodeURIComponent(strategyId)}/rule-groups/${groupId}/bindings/${bindingId}`,
  )
}
