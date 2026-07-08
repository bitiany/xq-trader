import type { TFunction } from 'i18next'

const TECHNICAL_TERM_KEYS: Record<string, string> = {
  偏多: 'stock.diagnosis.technical.trend.slightlyBullish',
  偏空: 'stock.diagnosis.technical.trend.slightlyBearish',
  中性: 'stock.diagnosis.technical.trend.neutral',
  多头: 'stock.diagnosis.technical.trend.bullish',
  空头: 'stock.diagnosis.technical.trend.bearish',
  震荡: 'stock.diagnosis.technical.trend.consolidation',
  上升趋势: 'stock.diagnosis.technical.trend.uptrend',
  下降趋势: 'stock.diagnosis.technical.trend.downtrend',
  金叉: 'stock.diagnosis.technical.signalValues.goldenCross',
  死叉: 'stock.diagnosis.technical.signalValues.deathCross',
  超买: 'stock.diagnosis.technical.signalValues.overbought',
  超卖: 'stock.diagnosis.technical.signalValues.oversold',
  净流入: 'stock.diagnosis.capitalFlow.trendInflow',
  净流出: 'stock.diagnosis.capitalFlow.trendOutflow',
  平衡: 'stock.diagnosis.capitalFlow.trendBalanced',
}

export function translateDiagnosisTerm(
  value: string | number | null | undefined,
  t: TFunction,
): string {
  if (value == null || value === '') return '—'
  const text = String(value)
  const key = TECHNICAL_TERM_KEYS[text]
  return key ? t(key) : text
}
