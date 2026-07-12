import type { MinuteBar } from '@/api/intraday'

export interface KlineBar {
  time: string
  open: number
  close: number
  high: number
  low: number
  volume: number
  /** 成交额（用于分时均线计算） */
  amount: number
}

export function minuteBarsToKline(bars: MinuteBar[]): KlineBar[] {
  return bars.map((b) => ({
    time: b.trade_time.substring(11, 16),
    open: b.open,
    close: b.close,
    high: b.high,
    low: b.low,
    volume: b.volume,
    amount: b.amount,
  }))
}

export function dailyBarsToKline(
  bars: { trade_date: string; open: number; close: number; high: number; low: number; volume: number; amount?: number }[],
): KlineBar[] {
  return bars.map((b) => ({
    time: b.trade_date,
    open: b.open,
    close: b.close,
    high: b.high,
    low: b.low,
    volume: b.volume,
    // 日线 amount 单位为千元，统一转为元；若缺失则按 close*volume*100 估算
    amount: b.amount != null ? b.amount * 1000 : b.close * b.volume * 100,
  }))
}

/**
 * 将 1m K线聚合为 N 分钟 K线
 * @param bars 1m K线数组（time 格式 "HH:MM"）
 * @param minutes 聚合周期（5/15 等）
 */
export function aggregateMinuteBars(bars: KlineBar[], minutes: number): KlineBar[] {
  if (bars.length === 0 || minutes <= 1) return bars
  const result: KlineBar[] = []
  let bucket: KlineBar[] = []
  let bucketKey = -1

  for (const bar of bars) {
    const [h, m] = bar.time.split(':').map(Number)
    const totalMin = h * 60 + m
    const key = Math.floor(totalMin / minutes)
    if (bucketKey === -1) bucketKey = key
    if (key !== bucketKey) {
      if (bucket.length > 0) result.push(mergeBars(bucket, bucketKey, minutes))
      bucket = []
      bucketKey = key
    }
    bucket.push(bar)
  }
  if (bucket.length > 0) result.push(mergeBars(bucket, bucketKey, minutes))
  return result
}

function mergeBars(bucket: KlineBar[], bucketKey: number, minutes: number): KlineBar {
  const first = bucket[0]
  const last = bucket[bucket.length - 1]
  const high = Math.max(...bucket.map((b) => b.high))
  const low = Math.min(...bucket.map((b) => b.low))
  const volume = bucket.reduce((sum, b) => sum + b.volume, 0)
  const amount = bucket.reduce((sum, b) => sum + b.amount, 0)
  const startMin = bucketKey * minutes
  const h = Math.floor(startMin / 60)
  const m = startMin % 60
  const timeLabel = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
  return {
    time: timeLabel,
    open: first.open,
    close: last.close,
    high,
    low,
    volume,
    amount,
  }
}

// ==================== 神奇九转 TD Sequential ====================

export interface TD9Result {
  /** 买入计数（1-9，正值表示连续下跌计数） */
  buySetup: (number | null)[]
  /** 卖出计数（1-9，正值表示连续上涨计数） */
  sellSetup: (number | null)[]
}

/**
 * 计算神奇九转 TD Sequential
 * 买入setup: 连续9根 close < 4根前close（下跌动能衰竭）
 * 卖出setup: 连续9根 close > 4根前close（上涨动能衰竭）
 */
export function calcTD9(bars: KlineBar[]): TD9Result {
  const buySetup: (number | null)[] = new Array(bars.length).fill(null)
  const sellSetup: (number | null)[] = new Array(bars.length).fill(null)
  let buyCount = 0
  let sellCount = 0

  for (let i = 0; i < bars.length; i++) {
    if (i < 4) continue
    const close = bars[i].close
    const refClose = bars[i - 4].close
    if (close > refClose) {
      sellCount = sellCount < 9 ? sellCount + 1 : 1
      buyCount = 0
      sellSetup[i] = sellCount
    } else if (close < refClose) {
      buyCount = buyCount < 9 ? buyCount + 1 : 1
      sellCount = 0
      buySetup[i] = buyCount
    } else {
      buyCount = 0
      sellCount = 0
    }
  }
  return { buySetup, sellSetup }
}

// ==================== 缠论（后端 API 返回） ====================

/** 缠论分型 */
export interface ChanlunFractal {
  /** K线索引 */
  index: number
  /** 交易日期/时间 */
  trade_date: string
  /** 分型价格 */
  price: number
  /** 方向：top=顶分型，bottom=底分型 */
  direction: 'top' | 'bottom'
}

/** 缠论笔 */
export interface ChanlunStroke {
  /** 起点索引 */
  start_index: number
  /** 终点索引 */
  end_index: number
  /** 起点价格 */
  start_price: number
  /** 终点价格 */
  end_price: number
  /** 方向：up=向上笔，down=向下笔 */
  direction: 'up' | 'down'
  /** 是否确认 */
  is_sure: boolean
}

/** 缠论中枢 */
export interface ChanlunPivot {
  /** 起点索引 */
  start_index: number
  /** 终点索引 */
  end_index: number
  /** 中枢上沿（ZG） */
  zg: number
  /** 中枢下沿（ZD） */
  zd: number
  /** 中枢中点（ZZ） */
  zz: number
  /** 是否确认 */
  is_sure: boolean
}

/** 缠论买卖点 */
export interface ChanlunBspPoint {
  /** K线索引 */
  index: number
  /** 交易日期/时间 */
  trade_date: string
  /** 价格 */
  price: number
  /** 是否买点：true=买点（向下笔终点底部），false=卖点（向上笔终点顶部） */
  is_buy: boolean
  /** 买卖点类型列表，如 ['1','2','3a'] */
  types: string[]
  /** 是否确认 */
  is_sure: boolean
}

/** 缠论完整数据 */
export interface ChanlunData {
  fractals: ChanlunFractal[]
  strokes: ChanlunStroke[]
  pivots: ChanlunPivot[]
  bs_points: ChanlunBspPoint[]
}

