import dayjs from 'dayjs'

export interface BacktestConfig {
  initialCapital: number
  commissionRate: number
  startDate: dayjs.Dayjs
  endDate: dayjs.Dayjs
  strategyId: string
}
