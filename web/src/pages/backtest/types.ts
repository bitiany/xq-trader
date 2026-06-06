import dayjs from 'dayjs'
import type { Combinator } from '@/api/strategy'

export type StrategyMode = 'builtin' | 'rule_combine' | 'expression' | 'alpha'

export interface RuleCombineConfig {
  rules: { rule_id: string; weight: number }[]
  buy_combinator: Combinator
  sell_combinator: Combinator
}

export interface BacktestConfig {
  initialCapital: number
  commissionRate: number
  stampDuty: number
  startDate: dayjs.Dayjs
  endDate: dayjs.Dayjs
  benchmark: string
  strategyMode: StrategyMode
  strategyId: string
  sizerId: string
  sizerParams: Record<string, unknown>
  alphaId: string | null
  alphaBuyThreshold: number
  alphaSellThreshold: number
  ruleCombineConfig: RuleCombineConfig
}

export const BENCHMARK_OPTIONS = [
  { value: '000300', label: '沪深300' },
  { value: '000905', label: '中证500' },
  { value: '000852', label: '中证1000' },
  { value: '000016', label: '上证50' },
]

export const STRATEGY_MODE_OPTIONS: { value: StrategyMode; label: string }[] = [
  { value: 'builtin', label: '内置策略' },
  { value: 'rule_combine', label: '规则组合' },
  { value: 'expression', label: '表达式策略' },
  { value: 'alpha', label: 'Alpha信号' },
]
