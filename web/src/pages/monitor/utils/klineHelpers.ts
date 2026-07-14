import type { MinuteBar } from '@/api/intraday'

export interface KlineBar {
  time: string
  /** 交易日期 YYYY-MM-DD，用于跨天聚合分桶 */
  date: string
  open: number
  close: number
  high: number
  low: number
  volume: number
  /** 成交额（用于分时均线计算） */
  amount: number
}

export function minuteBarsToKline(bars: MinuteBar[]): KlineBar[] {
  return bars.map((b) => {
    // trade_time 格式如 "2026-07-12T09:31:00+08:00"
    const fullTime = b.trade_time
    const date = fullTime.substring(0, 10)
    const time = fullTime.substring(11, 16)
    return {
      time,
      date,
      open: b.open,
      close: b.close,
      high: b.high,
      low: b.low,
      volume: b.volume,
      amount: b.amount,
    }
  })
}

export function dailyBarsToKline(
  bars: { trade_date: string; open: number; close: number; high: number; low: number; volume: number; amount?: number }[],
): KlineBar[] {
  return bars.map((b) => ({
    time: b.trade_date,
    date: b.trade_date,
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
 * 按 date + 时间桶 分桶，避免跨天同时段被合并
 * @param bars 1m K线数组
 * @param minutes 聚合周期（5/15 等）
 */
export function aggregateMinuteBars(bars: KlineBar[], minutes: number): KlineBar[] {
  if (bars.length === 0 || minutes <= 1) return bars
  const result: KlineBar[] = []
  let bucket: KlineBar[] = []
  let bucketKey = ''
  let bucketTimeBucket = -1 // 显式跟踪时间桶编号，避免从 key 字符串解析

  for (const bar of bars) {
    const [h, m] = bar.time.split(':').map(Number)
    const totalMin = h * 60 + m
    const timeBucket = Math.floor(totalMin / minutes)
    // key 包含日期，避免跨天同时段被合并到同一桶
    const key = `${bar.date}-${timeBucket}`
    if (bucketKey === '') {
      bucketKey = key
      bucketTimeBucket = timeBucket
    }
    if (key !== bucketKey) {
      if (bucket.length > 0) {
        result.push(mergeBars(bucket, bucket[0].date, bucketTimeBucket, minutes))
      }
      bucket = []
      bucketKey = key
      bucketTimeBucket = timeBucket
    }
    bucket.push(bar)
  }
  if (bucket.length > 0) {
    result.push(mergeBars(bucket, bucket[0].date, bucketTimeBucket, minutes))
  }
  return result
}

function mergeBars(bucket: KlineBar[], date: string, timeBucket: number, minutes: number): KlineBar {
  const first = bucket[0]
  const last = bucket[bucket.length - 1]
  const high = Math.max(...bucket.map((b) => b.high))
  const low = Math.min(...bucket.map((b) => b.low))
  const volume = bucket.reduce((sum, b) => sum + b.volume, 0)
  const amount = bucket.reduce((sum, b) => sum + b.amount, 0)
  const startMin = timeBucket * minutes
  const h = Math.floor(startMin / 60)
  const m = startMin % 60
  const timeLabel = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
  return {
    time: timeLabel,
    date,
    open: first.open,
    close: last.close,
    high,
    low,
    volume,
    amount,
  }
}

// ==================== 神奇九转 TD Sequential（后端 API 返回） ====================

/** 神奇九转数据，由后端 /stocks/{symbol}/td9 返回 */
export interface Td9Data {
  /** 买入计数（1-9，连续下跌动能衰竭） */
  buy_setup: (number | null)[]
  /** 卖出计数（1-9，连续上涨动能衰竭） */
  sell_setup: (number | null)[]
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

