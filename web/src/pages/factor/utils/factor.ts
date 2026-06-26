import type { FactorStatus } from '@/api'

export type FactorGrade = 'A' | 'B' | 'C' | 'D'

/** 等级 Tag 配色（独立色板，避免与红涨绿跌语义冲突；A=蓝 B=青 C=灰 D=红）。 */
export const GRADE_COLOR: Record<FactorGrade, string> = {
  A: 'blue',
  B: 'cyan',
  C: 'default',
  D: 'red',
}

/** 驾驶舱等级分布条配色（CSS 变量）。 */
export const GRADE_BAR_COLOR: Record<FactorGrade, string> = {
  A: 'var(--accent-primary)',
  B: '#13c2c2',
  C: 'var(--text-disabled, #bfbfbf)',
  D: 'var(--color-warning)',
}

export const GRADE_ORDER: FactorGrade[] = ['A', 'B', 'C', 'D']

export const STATUS_COLOR: Record<FactorStatus, string> = {
  active: 'success',
  testing: 'processing',
  draft: 'default',
  deprecated: 'error',
}

const PLACEHOLDER = '—'

/** 数值格式化，null/NaN → 占位符。 */
export function formatNum(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) return PLACEHOLDER
  return value.toFixed(digits)
}

/** 百分比格式化（输入为小数，如 0.1 → 10.00%）。 */
export function formatPct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return PLACEHOLDER
  return `${(value * 100).toFixed(digits)}%`
}

/** 距今天数描述。 */
export function daysAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return PLACEHOLDER
  const d = new Date(dateStr)
  if (Number.isNaN(d.getTime())) return PLACEHOLDER
  const diff = Math.floor((Date.now() - d.getTime()) / 86400000)
  if (diff <= 0) return '今日'
  return `${diff} 天前`
}

export function isUsableGrade(grade: string | null | undefined): boolean {
  return grade === 'A' || grade === 'B'
}
