import { request } from '@/api/client'
import type { ApiPageResult } from '@/api/types'

export type RuleCategory = 'cross_section' | 'time_series' | 'both'
export type RuleType = 'expression' | 'spi'
export type RuleStatus = 'draft' | 'active' | 'deprecated'

export interface SignalMapping {
  buy?: string | number | null
  sell?: string | number | null
  hold?: string | number | null
  [key: string]: unknown
}

export interface Rule {
  id?: number
  rule_id: string
  name: string
  category: RuleCategory
  type: RuleType
  expression: string | null
  spi_class: string | null
  factors: string[]
  signal_mapping: SignalMapping | null
  default_config: Record<string, unknown> | null
  description: string | null
  is_builtin: boolean
  status: RuleStatus
  created_at?: string
  updated_at?: string
}

export interface RuleListParams {
  page?: number
  page_size?: number
  category?: RuleCategory
  type?: RuleType
  status?: RuleStatus
  keyword?: string
}

export interface RuleCreatePayload {
  rule_id: string
  name: string
  category?: RuleCategory
  type?: RuleType
  expression: string
  factors: string[]
  signal_mapping?: SignalMapping
  default_config?: Record<string, unknown>
  description?: string
  status?: RuleStatus
}

export interface RuleUpdatePayload {
  name?: string
  expression?: string
  factors?: string[]
  signal_mapping?: SignalMapping
  default_config?: Record<string, unknown>
  description?: string
  status?: RuleStatus
}

export interface RuleFactorDep {
  rule_id: string
  factor_id: string
  required: boolean
  description?: string | null
}

export async function fetchRules(params: RuleListParams = {}): Promise<ApiPageResult<Rule>> {
  return request.get<ApiPageResult<Rule>>('/rules', { params })
}

export async function createRule(payload: RuleCreatePayload): Promise<Rule> {
  return request.post<Rule>('/rules', payload)
}

export async function updateRule(ruleId: string, payload: RuleUpdatePayload): Promise<Rule> {
  return request.put<Rule>(`/rules/${encodeURIComponent(ruleId)}`, payload)
}

export async function fetchRuleDetail(ruleId: string): Promise<Rule> {
  return request.get<Rule>(`/rules/${encodeURIComponent(ruleId)}`)
}

export async function fetchRuleFactors(ruleId: string): Promise<RuleFactorDep[]> {
  return request.get<RuleFactorDep[]>(`/rules/${encodeURIComponent(ruleId)}/factors`)
}
