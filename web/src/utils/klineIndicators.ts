import type { IndicatorKind, KlineBarItem } from '@/api/stock'

export type OverlaySeries = Record<string, Array<number | null>>

function sma(values: number[], period: number): Array<number | null> {
  const out: Array<number | null> = []
  for (let i = 0; i < values.length; i++) {
    if (i + 1 < period) {
      out.push(null)
      continue
    }
    const window = values.slice(i + 1 - period, i + 1)
    out.push(window.reduce((a, b) => a + b, 0) / period)
  }
  return out
}

function ema(values: number[], period: number): Array<number | null> {
  if (values.length === 0) {
    return []
  }
  const k = 2 / (period + 1)
  const out: Array<number | null> = Array(values.length).fill(null)
  out[period - 1] = values.slice(0, period).reduce((a, b) => a + b, 0) / period
  for (let i = period; i < values.length; i++) {
    const prev = out[i - 1]
    if (prev == null) {
      out[i] = null
    } else {
      out[i] = values[i] * k + prev * (1 - k)
    }
  }
  return out
}

function calcMa(closes: number[]): OverlaySeries {
  return {
    ma5: sma(closes, 5),
    ma10: sma(closes, 10),
    ma20: sma(closes, 20),
    ma60: sma(closes, 60),
  }
}

function calcMacd(closes: number[]): OverlaySeries {
  const ema12 = ema(closes, 12)
  const ema26 = ema(closes, 26)
  const dif: Array<number | null> = []
  for (let i = 0; i < closes.length; i++) {
    const a = ema12[i]
    const b = ema26[i]
    dif.push(a != null && b != null ? a - b : null)
  }
  const difFilled = dif.map((v) => v ?? 0)
  const dea = ema(difFilled, 9)
  const macd: Array<number | null> = []
  for (let i = 0; i < closes.length; i++) {
    const d = dif[i]
    const e = dea[i]
    macd.push(d != null && e != null ? (d - e) * 2 : null)
  }
  return { dif, dea, macd }
}

function calcKdj(bars: KlineBarItem[], n = 9): OverlaySeries {
  const k: Array<number | null> = []
  const d: Array<number | null> = []
  const j: Array<number | null> = []
  let prevK = 50
  let prevD = 50
  for (let i = 0; i < bars.length; i++) {
    const start = Math.max(0, i - n + 1)
    const window = bars.slice(start, i + 1)
    const lowN = Math.min(...window.map((b) => b.low))
    const highN = Math.max(...window.map((b) => b.high))
    const rsv = highN === lowN ? 50 : ((bars[i].close - lowN) / (highN - lowN)) * 100
    const curK = (prevK * 2) / 3 + rsv / 3
    const curD = (prevD * 2) / 3 + curK / 3
    const curJ = 3 * curK - 2 * curD
    prevK = curK
    prevD = curD
    if (i + 1 < n) {
      k.push(null)
      d.push(null)
      j.push(null)
    } else {
      k.push(Math.round(curK * 10000) / 10000)
      d.push(Math.round(curD * 10000) / 10000)
      j.push(Math.round(curJ * 10000) / 10000)
    }
  }
  return { k, d, j }
}

function calcRsi(closes: number[], period = 14): OverlaySeries {
  const rsi: Array<number | null> = Array(closes.length).fill(null)
  if (closes.length < period + 1) {
    return { rsi14: rsi }
  }
  const gains: number[] = []
  const losses: number[] = []
  for (let i = 1; i < closes.length; i++) {
    const delta = closes[i] - closes[i - 1]
    gains.push(Math.max(delta, 0))
    losses.push(Math.max(-delta, 0))
  }
  let avgGain = gains.slice(0, period).reduce((a, b) => a + b, 0) / period
  let avgLoss = losses.slice(0, period).reduce((a, b) => a + b, 0) / period
  rsi[period] = avgLoss === 0 ? 100 : Math.round((100 - 100 / (1 + avgGain / avgLoss)) * 10000) / 10000
  for (let i = period + 1; i < closes.length; i++) {
    avgGain = (avgGain * (period - 1) + gains[i - 1]) / period
    avgLoss = (avgLoss * (period - 1) + losses[i - 1]) / period
    rsi[i] = avgLoss === 0 ? 100 : Math.round((100 - 100 / (1 + avgGain / avgLoss)) * 10000) / 10000
  }
  return { rsi14: rsi }
}

function calcBias(closes: number[]): OverlaySeries {
  const result: OverlaySeries = {}
  for (const period of [6, 12, 24]) {
    const ma = sma(closes, period)
    result[`bias${period}`] = closes.map((close, i) => {
      const m = ma[i]
      if (m == null || m === 0) {
        return null
      }
      return Math.round(((close - m) / m) * 10000) / 10000
    })
  }
  return result
}

export function computeOverlays(bars: KlineBarItem[], indicator: IndicatorKind): OverlaySeries {
  const closes = bars.map((b) => b.close)
  if (indicator === 'ma') {
    return calcMa(closes)
  }
  if (indicator === 'macd') {
    return calcMacd(closes)
  }
  if (indicator === 'kdj') {
    return calcKdj(bars)
  }
  if (indicator === 'rsi') {
    return calcRsi(closes)
  }
  return calcBias(closes)
}

function seriesHasData(values: Array<number | null> | undefined): boolean {
  return Boolean(values?.some((v) => v != null && !Number.isNaN(v)))
}

/** 优先使用 API 因子；缺失时用 K 线本地计算 */
export function resolveOverlays(
  bars: KlineBarItem[],
  indicator: IndicatorKind,
  apiOverlays: OverlaySeries,
): OverlaySeries {
  const local = computeOverlays(bars, indicator)
  const merged: OverlaySeries = { ...local }
  for (const [key, values] of Object.entries(apiOverlays)) {
    if (seriesHasData(values)) {
      merged[key] = values
    }
  }
  return merged
}

export function resolveMaOverlays(bars: KlineBarItem[], apiMa: OverlaySeries): OverlaySeries {
  const local = calcMa(bars.map((b) => b.close))
  const merged: OverlaySeries = { ...local }
  for (const [key, values] of Object.entries(apiMa)) {
    if (seriesHasData(values)) {
      merged[key] = values
    }
  }
  return merged
}
