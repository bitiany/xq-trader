export function computeMA(data: number[], period: number): (number | null)[] {
  const result: (number | null)[] = []
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) {
      result.push(null)
    } else {
      let sum = 0
      for (let j = 0; j < period; j++) {
        sum += data[i - j]
      }
      result.push(sum / period)
    }
  }
  return result
}

export function computeEMA(data: number[], period: number): (number | null)[] {
  const result: (number | null)[] = []
  const k = 2 / (period + 1)
  let ema: number | null = null
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) {
      result.push(null)
    } else if (i === period - 1) {
      let sum = 0
      for (let j = 0; j < period; j++) sum += data[i - j]
      ema = sum / period
      result.push(ema)
    } else {
      ema = data[i] * k + (ema ?? 0) * (1 - k)
      result.push(ema)
    }
  }
  return result
}

export function computeMACD(closes: number[], short = 12, long = 26, signal = 9) {
  const emaShort = computeEMA(closes, short)
  const emaLong = computeEMA(closes, long)
  const dif: (number | null)[] = []
  for (let i = 0; i < closes.length; i++) {
    if (emaShort[i] == null || emaLong[i] == null) {
      dif.push(null)
    } else {
      dif.push(emaShort[i]! - emaLong[i]!)
    }
  }
  const difValues = dif.filter((v) => v != null) as number[]
  const deaRaw = computeEMA(difValues, signal)
  const dea: (number | null)[] = []
  let di = 0
  for (let i = 0; i < closes.length; i++) {
    if (dif[i] == null) {
      dea.push(null)
    } else {
      dea.push(deaRaw[di] ?? null)
      di++
    }
  }
  const macdBar: (number | null)[] = []
  for (let i = 0; i < closes.length; i++) {
    if (dif[i] == null || dea[i] == null) {
      macdBar.push(null)
    } else {
      macdBar.push((dif[i]! - dea[i]!) * 2)
    }
  }
  return { dif, dea, macdBar }
}

export async function loadKlineData(symbol: string) {
  const { fetchStockKlineBars, fetchStockChanlun } = await import('@/api/stock')
  const [klineResp, chanlunResp] = await Promise.all([
    fetchStockKlineBars(symbol).catch(() => []),
    fetchStockChanlun(symbol).catch(() => undefined),
  ])
  return {
    klineBars: Array.isArray(klineResp) ? klineResp : [],
    chanlunData: chanlunResp ?? undefined,
  }
}
