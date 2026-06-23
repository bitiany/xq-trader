import { request } from '@/api/client'
import type { ApiPageResult } from '@/api/types'

export type RuleCategory = 'selection' | 'timing' | 'both'
export type RuleType = 'expression' | 'plugin'
export type RuleStatus = 'active' | 'deprecated'

export interface Rule {
  id?: number
  rule_id: string
  name: string
  category: RuleCategory
  rule_type: RuleType
  definition: Record<string, unknown>
  factors: string[]
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
  rule_type?: RuleType
  status?: RuleStatus
  keyword?: string
}

export interface RuleCreatePayload {
  rule_id: string
  name: string
  category?: RuleCategory
  rule_type?: RuleType
  definition: Record<string, unknown>
  factors: string[]
  description?: string
  status?: RuleStatus
}

export interface RuleUpdatePayload {
  name?: string
  category?: RuleCategory
  definition?: Record<string, unknown>
  factors?: string[]
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
