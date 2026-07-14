/**
 * 后端统一计算的技术指标数据结构
 * 对应后端 StockIndicatorService.get_indicators() 返回结构
 * 前端不再实现任何指标计算函数，全部从后端 API 获取
 */

export interface MacdData {
  /** DIF 线（快线-慢线） */
  dif: (number | null)[]
  /** DEA 线（DIF 的 signal 周期 EMA） */
  dea: (number | null)[]
  /** MACD 柱值 (DIF - DEA) * 2 */
  macd: (number | null)[]
}

export interface BollData {
  upper: (number | null)[]
  mid: (number | null)[]
  lower: (number | null)[]
}

export interface DonchianData {
  upper: (number | null)[]
  lower: (number | null)[]
}

export interface IndicatorData {
  /** MA5 简单移动平均 */
  ma5?: (number | null)[]
  /** MA20 简单移动平均 */
  ma20?: (number | null)[]
  /** 布林带 */
  boll?: BollData | null
  /** 唐奇安通道 */
  donchian?: DonchianData | null
  /** MACD 指标 */
  macd?: MacdData
  /** RSI(14) */
  rsi?: (number | null)[]
  /** VWAP 累计均价（仅 1m 周期） */
  vwap?: number[]
  /** TWAP 累计典型价均值（仅 1m 周期） */
  twap?: number[]
}
